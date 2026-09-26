# argocd-gitops-platform

Déploiement continu GitOps sur un cluster Kubernetes kubeadm avec Argo CD : le dépôt Git est l'unique source de vérité, et Argo CD aligne en continu le cluster sur son contenu (synchronisation automatique, self-heal, prune, rollback par `git revert`).

> **Statut :** projet en cours de construction (Phase 4 terminée — Argo CD v3.4.9 installé ; podinfo pas encore déployé).

## Environnement

| Élément | Valeur |
| ------- | ------ |
| Cluster | kubeadm, 1 control-plane + 2 workers, Kubernetes v1.32 |
| Nœuds | Ubuntu 22.04, containerd, réseau host-only `192.168.56.0/24` |
| CNI | Calico |
| Stockage | local-path-provisioner |
| Argo CD | v3.4.9, version épinglée (compatible Kubernetes 1.32) |

Détail de l'environnement, contraintes connues et architecture cible : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Structure du dépôt

La structure sera complétée au fil des phases :

```
argocd-gitops-platform/
├── apps/          # manifestes des applications (Kustomize)
├── argocd/        # installation d'Argo CD, AppProjects, Applications
├── docs/          # architecture, sécurité, décisions, scénarios GitOps, troubleshooting
├── screenshots/   # preuves commentées
└── scripts/       # validation et réinitialisation du laboratoire
```

## Preuves

### Point de départ : un cluster sans Argo CD

![Cluster initial avant installation d'Argo CD](screenshots/01-cluster-initial.png)

Le projet démarre sur un cluster kubeadm de trois nœuds `Ready` (Kubernetes v1.32.13) qui ne contient que ses composants système : Calico (CNI), local-path-provisioner (stockage) et les namespaces Kubernetes par défaut. Aucun namespace `argocd` et aucune CRD `argoproj.io` : Argo CD n'est pas encore installé.

Cet état initial est vérifié plutôt que supposé, pour deux raisons. D'abord, les CRDs d'Argo CD sont des ressources cluster-scoped : une installation antérieure laisserait des CRDs d'une autre version qui cohabiteraient mal avec la version installée ensuite (v3.4.9, épinglée). Ensuite, ce point de départ sert de référence pour prouver la reproductibilité du projet : la réinitialisation du laboratoire devra ramener le cluster exactement à cet état.

### Capacité et réseau : les contraintes qui orientent la conception

![Capacité des nœuds, pool Calico et classes du cluster](screenshots/02-cluster-capacite-reseau.png)

Cette capture relève les contraintes sur lesquelles reposent trois choix du projet (`k` est un alias de `kubectl1.33`, client choisi pour respecter la compatibilité à une version mineure près avec l'API server 1.32).

* **Capacité.** Les workers disposent d'1 vCPU et de 2 Gio chacun, dont 64 à 65 % de mémoire déjà occupée au repos, et le control-plane porte le taint `NoSchedule` : tout ce que le projet déploie tiendra sur les deux workers. D'où Argo CD en mode non-HA et des `requests`/`limits` bornés pour `podinfo`.
* **Réseau.** Calico alloue les IP des pods dans le pool `192.168.0.0/16`, avec encapsulation VXLAN uniquement entre sous-réseaux différents (`CrossSubnet`) ; les nœuds partageant `192.168.56.0/24`, le trafic entre pods est routé sans encapsulation. Les `PODCIDR` affichés par nœud ne sont pas utilisés : Calico gère sa propre IPAM. Le pool englobe le réseau des nœuds : ce chevauchement est documenté comme contrainte connue, sans correction, le CNI étant hors du périmètre du projet.
* **Exposition.** La dernière commande ne renvoie aucune IngressClass, seulement la StorageClass `local-path` : il n'existe aucun point d'entrée HTTP dans le cluster, et aucun LoadBalancer n'est disponible hors cloud. L'interface d'Argo CD sera donc consultée par `kubectl port-forward`, sans rien exposer au-delà du poste d'administration.

Le détail et les autres contraintes relevées (dont la latence d'etcd) figurent dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Manifestes de podinfo validés avant tout déploiement

![Rendu Kustomize et validation kubeconform des manifestes de podinfo](screenshots/03-podinfo-manifestes-valides.png)

Les manifestes de `podinfo` (`apps/podinfo/base/`) sont rendus par Kustomize puis validés contre le schéma exact de Kubernetes 1.32, sans aucun accès au cluster : rien n'est appliqué à la main, c'est Argo CD qui déploiera ce rendu. La première commande extrait du rendu les propriétés qui portent la sécurité de l'application :

* **`enforce: restricted`** sur le namespace : Pod Security Admission refuse tout pod qui tournerait en root, garderait des capabilities ou autoriserait l'escalade de privilèges. C'est une seconde barrière, indépendante des manifestes : même une erreur commitée dans Git ne pourrait pas lancer un pod privilégié dans ce namespace.
* **Image épinglée par digest** : le tag `6.15.0` reste lisible, mais c'est le digest `sha256:…` de l'index multi-architecture qui fait foi. Un tag republié côté registre ne peut pas changer silencieusement ce qui tourne dans le cluster, et le déploiement est reproductible.
* **`runAsUser: 100`** : l'image déclare un utilisateur par son nom (`USER app`), que le kubelet ne peut pas vérifier ; sans UID numérique, `runAsNonRoot` ferait refuser le pod. L'UID 100 a été relevé dans l'image elle-même.
* **`readOnlyRootFilesystem: true`** : un attaquant qui prendrait la main sur le processus ne pourrait ni modifier le binaire ni déposer d'outil ; seul un volume `emptyDir` de 16 Mio monté sur `/data` est inscriptible. Ce fonctionnement a été testé en local avant d'être déclaré.

La seconde commande valide les trois ressources en mode `-strict` : un champ inconnu, par exemple une faute de frappe dans `readOnlyRootFilesystem`, est rejeté au lieu d'être ignoré silencieusement par l'API server, ce qui aurait désactivé le durcissement sans aucun message d'erreur.

### Argo CD v3.4.9 installé de façon déclarative et épinglée

![Pods Argo CD Running sur les workers et CRDs enregistrées](screenshots/04-argocd-pods-running.png)

Argo CD est installé par la seule opération impérative du projet :

```
kustomize build argocd/bootstrap | kubectl1.33 --context gitops-kubeadm apply --server-side -f -
```

`argocd/bootstrap/` référence le manifeste officiel non modifié, épinglé par le SHA du commit du tag `v3.4.9` (un tag Git peut être déplacé, un commit non), et y ajoute le namespace `argocd`. L'installation a d'abord été simulée avec `--dry-run=server`, qui fait passer chaque objet par l'authentification, le RBAC, la validation et l'admission de l'API server sans rien écrire dans etcd.

`--server-side` n'est pas un choix de confort : en apply classique, `kubectl` recopie chaque objet dans l'annotation `last-applied-configuration`, limitée à 256 Kio, alors que les CRDs `applications` (397 Ko) et `applicationsets` (1,39 Mo) la dépassent. Avec Server-Side Apply, c'est l'API server qui calcule la fusion et suit la propriété de chaque champ (`managedFields`).

La capture montre les sept composants `Running` sans redémarrage et les trois CRDs qui étendent l'API Kubernetes (`Application`, `ApplicationSet`, `AppProject`). Aucun pod ne tourne sur `k8s-master` : le taint `NoSchedule` du control-plane repousse toute la charge sur les workers, conformément à [l'architecture](docs/ARCHITECTURE.md). Le namespace `argocd` impose le profil Pod Security `restricted`, et les sept pods ont été admis : tous tournent sans root, sans capability et avec une racine en lecture seule. Les sept NetworkPolicies du manifeste officiel sont appliquées par Calico et cloisonnent les composants dès l'installation.

![Images Argo CD v3.4.9 et consommation mémoire des pods](screenshots/05-argocd-version-ressources.png)

La première commande liste l'image de chaque composant : `quay.io/argoproj/argocd:v3.4.9` partout, plus Dex et Redis aux versions fixées par ce manifeste. La version qui tourne est donc bien celle décidée, et non une `latest` récupérée au passage.

La seconde mesure le coût réel d'Argo CD au repos, sans aucune Application : environ 150 Mio pour sept pods répartis sur deux workers. Dex, le connecteur SSO, en représente à lui seul environ 45 Mio alors qu'aucun SSO n'est configuré : c'est la première économie possible si la mémoire venait à manquer. La mesure se fait par pod (`top pods`) et non par nœud : le *working set* d'un nœud inclut une partie du cache disque du noyau, qui a justement baissé pendant le téléchargement des images, et ne reflète pas la consommation d'Argo CD.

## Licence

[MIT](LICENSE)
