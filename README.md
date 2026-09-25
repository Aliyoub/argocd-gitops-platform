# argocd-gitops-platform

Déploiement continu GitOps sur un cluster Kubernetes kubeadm avec Argo CD : le dépôt Git est l'unique source de vérité, et Argo CD aligne en continu le cluster sur son contenu (synchronisation automatique, self-heal, prune, rollback par `git revert`).

> **Statut :** projet en cours de construction (Phase 1 terminée — dépôt initialisé).

## Environnement

| Élément | Valeur |
| ------- | ------ |
| Cluster | kubeadm, 1 control-plane + 2 workers, Kubernetes v1.32 |
| Nœuds | Ubuntu 22.04, containerd, réseau host-only `192.168.56.0/24` |
| CNI | Calico |
| Stockage | local-path-provisioner |
| Argo CD | v3.4.9, version épinglée (compatible Kubernetes 1.32) |

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

## Licence

[MIT](LICENSE)
