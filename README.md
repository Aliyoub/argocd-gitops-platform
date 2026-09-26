# argocd-gitops-platform

Déploiement continu GitOps sur un cluster Kubernetes kubeadm avec Argo CD : le dépôt Git est l'unique source de vérité, et Argo CD aligne en continu le cluster sur son contenu (synchronisation automatique, self-heal, prune, rollback par `git revert`).

> **Statut :** projet en cours de construction (Phase 2 terminée — environnement documenté).

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

## Licence

[MIT](LICENSE)
