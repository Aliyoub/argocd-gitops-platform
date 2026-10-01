#!/usr/bin/env python3
"""Vérifie les règles de sécurité et de reproductibilité des applications.

Usage : kustomize build apps/podinfo/base | scripts/check-policies.py

Règles, pour chaque conteneur d'une charge de travail :
- image épinglée par digest (@sha256:...), jamais « latest » ;
- requests et limits CPU et mémoire déclarées ;
- exécution non-root, sans escalade de privilèges, racine en lecture seule,
  capabilities supprimées (ALL).

Ne s'applique qu'aux applications du dépôt (apps/), pas au manifeste officiel
d'Argo CD, qui n'est pas modifié.
"""
import sys

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "Pod"}


def pod_spec(doc):
    if doc["kind"] == "Pod":
        return doc.get("spec", {})
    return doc["spec"]["template"]["spec"]


def check_container(name, container, pod_sc):
    errors = []
    image = container.get("image", "")
    if image.endswith(":latest") or ":" not in image.split("/")[-1]:
        errors.append(f"image « {image} » : tag « latest » ou absent")
    if "@sha256:" not in image:
        errors.append(f"image « {image} » : non épinglée par digest")
    resources = container.get("resources", {})
    for section in ("requests", "limits"):
        for key in ("cpu", "memory"):
            if key not in resources.get(section, {}):
                errors.append(f"resources.{section}.{key} manquant")
    sc = container.get("securityContext", {})
    if not sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot")):
        errors.append("runAsNonRoot non activé")
    if sc.get("allowPrivilegeEscalation") is not False:
        errors.append("allowPrivilegeEscalation doit valoir false")
    if sc.get("readOnlyRootFilesystem") is not True:
        errors.append("readOnlyRootFilesystem doit valoir true")
    if "ALL" not in sc.get("capabilities", {}).get("drop", []):
        errors.append("capabilities.drop doit contenir ALL")
    return [f"{name} : {error}" for error in errors]


def main():
    errors = []
    checked = 0
    for doc in yaml.safe_load_all(sys.stdin):
        if not doc or doc.get("kind") not in WORKLOADS:
            continue
        spec = pod_spec(doc)
        pod_sc = spec.get("securityContext", {})
        for container in spec.get("initContainers", []) + spec.get("containers", []):
            name = f"{doc['kind']}/{doc['metadata']['name']} conteneur {container['name']}"
            errors.extend(check_container(name, container, pod_sc))
            checked += 1
    if checked == 0:
        sys.exit("aucun conteneur trouvé sur l'entrée standard")
    # flush : sans terminal (CI), stdout est mis en tampon alors que le bilan
    # part sur stderr sans tampon ; il s'afficherait avant les détails.
    for error in errors:
        print(f"  ÉCHEC {error}", flush=True)
    if errors:
        sys.exit(f"{len(errors)} règle(s) non respectée(s) sur {checked} conteneur(s)")
    print(f"{checked} conteneur(s) conforme(s)")


if __name__ == "__main__":
    main()
