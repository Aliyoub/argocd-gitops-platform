# argocd-gitops-platform

Déploiement continu GitOps sur un cluster Kubernetes kubeadm avec Argo CD : le dépôt Git est l'unique source de vérité, et Argo CD aligne en continu le cluster sur son contenu (synchronisation automatique, self-heal, prune, rollback par `git revert`).

> **Statut :** projet en cours de construction (Phase 3 terminée — manifestes de podinfo validés, pas encore déployés).

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

## Licence

[MIT](LICENSE)
