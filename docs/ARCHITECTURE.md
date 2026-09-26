# Architecture

Ce document décrit l'environnement sur lequel le projet est construit et l'architecture GitOps visée. Les valeurs de la section « Environnement » ont été relevées sur le cluster le 2026-09-26 (commandes en lecture seule, sorties non retouchées) ; elles ne sont pas supposées.

## Vue d'ensemble

```
   Développeur
       |
       | git push / pull request
       v
   GitHub (argocd-gitops-platform)
       |                     \
       |                      GitHub Actions
       |                      (validation des manifestes, aucun accès au cluster)
       | pull (HTTPS, polling)
       v
+---------------------- Cluster kubeadm ----------------------+
|                                                             |
|  namespace argocd                                           |
|    Argo CD v3.4.9 (version épinglée)                        |
|    AppProject "podinfo" (sources et destinations            |
|    restreintes)                                             |
|    Application racine (App of Apps)                         |
|         |                                                   |
|         v                                                   |
|  namespace podinfo                                          |
|    Deployment (replicas, probes, ressources)                |
|    Service (ClusterIP)                                      |
+-------------------------------------------------------------+
        ^
        | kubectl port-forward (poste local uniquement)
   Navigateur / CLI argocd
```

Le modèle est **pull** : c'est Argo CD, dans le cluster, qui lit Git et applique l'état déclaré. La CI valide les manifestes mais ne détient aucune credential du cluster ; compromettre le pipeline ne donne donc pas la main sur le cluster.

## Environnement

### Hébergement

Trois VM VirtualBox sur un poste macOS, reliées par un réseau host-only `192.168.56.0/24`. Aucun fournisseur cloud : pas de LoadBalancer, pas de DNS public, pas de coût.

### Nœuds

| Nœud | Rôle | IP | vCPU | Mémoire | Taint |
| ---- | ---- | -- | ---- | ------- | ----- |
| `k8s-master` | control-plane | 192.168.56.10 | 2 | 2 Gio | `node-role.kubernetes.io/control-plane:NoSchedule` |
| `k8s-worker1` | worker | 192.168.56.20 | 1 | 2 Gio | aucun |
| `k8s-worker2` | worker | 192.168.56.21 | 1 | 2 Gio | aucun |

Tous les nœuds : Ubuntu 22.04.5 LTS, containerd 2.2.1, kubelet v1.32.13. Le control-plane (kube-apiserver, etcd, scheduler, controller-manager) tourne en pods statiques kubeadm sur `k8s-master`.

### Réseau

| Élément | Valeur |
| ------- | ------ |
| CNI | Calico, géré par tigera-operator (`tigerastatus` : `apiserver`, `calico`, `ippools` disponibles) |
| Pool d'IP des pods | `192.168.0.0/16`, blocs `/26` par nœud, `natOutgoing` activé |
| Encapsulation | VXLAN `CrossSubnet` (pas d'encapsulation entre nœuds du même sous-réseau), IP-in-IP désactivé, BGP activé |
| Plage des Services | `10.96.0.0/12` |
| Blocs IPAM alloués | `192.168.235.192/26` (master), `192.168.194.64/26` (worker1), `192.168.126.0/26` (worker2) |
| `spec.podCIDR` des nœuds | `192.168.0.0/24`, `192.168.1.0/24`, `192.168.2.0/24` : attribués par kube-controller-manager mais **non utilisés**, Calico gérant sa propre IPAM (`ipam.type: Calico`) |
| IngressClass | aucune |
| Service `LoadBalancer` | aucun |

Calico applique les NetworkPolicy Kubernetes : c'est ce qui rend pertinente l'extension NetworkPolicy prévue pour `podinfo`.

### Stockage

StorageClass `local-path` (par défaut), provisionneur `rancher.io/local-path`, `reclaimPolicy: Delete`, `WaitForFirstConsumer`. Les volumes sont des répertoires locaux au nœud : ils ne survivent pas à la perte du nœud. Le projet n'en a pas besoin (Argo CD en mode non-HA et `podinfo` sont sans état persistant).

### Composants présents avant le projet

| Namespace | Composant | Rôle |
| --------- | --------- | ---- |
| `kube-system` | etcd, kube-apiserver, kube-scheduler, kube-controller-manager, kube-proxy, CoreDNS | control-plane et services de base |
| `kube-system` | metrics-server | métriques CPU/mémoire (`kubectl top`) |
| `tigera-operator` | tigera-operator | cycle de vie de Calico |
| `calico-system`, `calico-apiserver` | calico-node, typha, kube-controllers, csi-node-driver, API Calico | réseau des pods et NetworkPolicy |
| `local-path-storage` | local-path-provisioner | volumes persistants locaux |

CRDs présentes : 19 `crd.projectcalico.org`, 4 `operator.tigera.io`, 1 `policy.networking.k8s.io`. Aucune CRD `argoproj.io`.

## Périmètre du projet

Le projet ne crée et ne modifie que ses propres ressources :

| Ressource | Périmètre |
| --------- | --------- |
| namespace `argocd` et son contenu | installé en Phase 4 |
| CRDs `*.argoproj.io` et ClusterRoles/ClusterRoleBindings d'Argo CD | cluster-scoped, installés avec Argo CD, inventoriés avant toute suppression |
| namespace `podinfo` et son contenu | géré par Argo CD depuis `apps/podinfo/` |

Hors périmètre, jamais modifiés : `kube-system`, `kube-public`, `kube-node-lease`, `calico-*`, `tigera-operator`, `local-path-storage`, les nœuds, kubeadm, le CNI et le kubeconfig. La réinitialisation du laboratoire (Phase 11) doit ramener le cluster à l'état décrit ci-dessus.

## Conséquences sur la conception

**Accès à l'interface par `port-forward`.** Sans IngressClass ni LoadBalancer, exposer Argo CD demanderait d'installer un contrôleur Ingress ou d'ouvrir un NodePort sur le réseau host-only. `kubectl port-forward` limite l'accès au poste qui détient le kubeconfig et réutilise son authentification : c'est la surface d'exposition minimale (décision D3).

**Polling Git plutôt que webhook.** Le cluster n'est pas joignable depuis Internet : un webhook GitHub ne peut pas atteindre Argo CD sans exposition. Argo CD interroge donc le dépôt périodiquement : en v3.4.9, toutes les 120 secondes, plus un décalage aléatoire (jitter) de 0 à 60 secondes qui étale la charge sur le repo-server (`timeout.reconciliation` et `timeout.reconciliation.jitter` dans `argocd-cm`). Le délai entre un commit et la synchronisation est un compromis assumé.

**Placement sur les workers.** Le taint `NoSchedule` du control-plane repousse Argo CD et `podinfo` sur les deux workers : 1 vCPU et 2 Gio chacun, dont 64 à 65 % de mémoire déjà utilisée au repos (`kubectl top nodes`, relevés du 2026-09-26). Mesurée après installation, la consommation d'Argo CD au repos est d'environ 150 Mio pour sept pods (`kubectl top pods`, sans aucune Application), dont environ 45 Mio pour Dex, inutile sans SSO. Elle augmentera avec le nombre d'Applications et de ressources suivies. Le mode non-HA est retenu et les ressources de `podinfo` sont bornées pour préserver cette marge.

## Contraintes connues

### Latence d'etcd et redémarrages du control-plane

Constat du 2026-09-26 : en 18 jours, kube-controller-manager a redémarré 63 fois, kube-scheduler 64 fois, tigera-operator 49 fois et kube-apiserver 13 fois. Le dernier épisode (06:38 UTC) se lit dans les journaux :

1. etcd répond lentement (193 avertissements `apply request took too long` en 30 minutes, jusqu'à 670 ms pour 100 ms attendus) ;
2. kube-apiserver dépasse ses délais (`http: Handler timeout`) ;
3. kube-controller-manager et kube-scheduler ne renouvellent plus leur lease (`failed to renew lease ... context deadline exceeded`) et s'arrêtent volontairement (`leaderelection lost`, code 1) : c'est le comportement prévu, qui empêche deux instances de se croire leader ;
4. kube-apiserver échoue à ses sondes et est redémarré par le kubelet (code 137).

Le cluster revient `Ready` seul en une à deux minutes. Cause racine probable : etcd, très sensible à la latence des écritures disque (`fsync`), sur une VM VirtualBox de 2 vCPU et 2 Gio (67 à 73 % de mémoire utilisée selon les relevés). L'origine exacte (disque virtuel, contention CPU de l'hôte) n'est pas vérifiée ; la mise en veille du poste est écartée pour cet épisode (dernier réveil à 07:36 locale, incident à 08:38 locale).

Impact sur le projet : Argo CD dépend de l'API Kubernetes. Pendant un épisode, la synchronisation est retardée, puis reprend ; l'état déclaré dans Git n'est pas affecté. Ce comportement sert de cas réel pour `docs/TROUBLESHOOTING.md`.

### Chevauchement du pool de pods et du réseau des nœuds

Le pool Calico `192.168.0.0/16` englobe le réseau host-only `192.168.56.0/24` des nœuds. Aucun bloc alloué ne tombe aujourd'hui dans `192.168.56.0/24`, mais Calico pourrait en attribuer un si un nœud dépassait les 64 adresses de son bloc actuel, ce qui créerait un conflit de routage avec les IP des nœuds. Le risque est faible à l'échelle du projet. La correction (pool excluant `192.168.56.0/24`) toucherait le CNI, hors périmètre : la contrainte est documentée, pas corrigée. Sur un cluster neuf, le `--pod-network-cidr` serait choisi disjoint du réseau des nœuds.
