#!/usr/bin/env python3
"""Génère les schémas JSON kubeconform des CRDs lues sur l'entrée standard.

Usage : kustomize build argocd/bootstrap | scripts/crd-schemas.py <répertoire>

Les schémas viennent des CRDs du manifeste Argo CD épinglé : ils correspondent
exactement à la version installée, sans dépendre d'un catalogue tiers. Chaque
objet déclarant des propriétés reçoit « additionalProperties: false », pour que
kubeconform -strict rejette les champs inconnus (fautes de frappe).
"""
import json
import os
import sys

import yaml


def strict(node):
    if isinstance(node, dict):
        if (
            node.get("type") == "object"
            and "properties" in node
            and "additionalProperties" not in node
            and not node.get("x-kubernetes-preserve-unknown-fields")
        ):
            node["additionalProperties"] = False
        for value in node.values():
            strict(value)
    elif isinstance(node, list):
        for value in node:
            strict(value)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage : crd-schemas.py <répertoire de sortie>")
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for doc in yaml.safe_load_all(sys.stdin):
        if not doc or doc.get("kind") != "CustomResourceDefinition":
            continue
        kind = doc["spec"]["names"]["kind"].lower()
        for version in doc["spec"]["versions"]:
            schema = version["schema"]["openAPIV3Schema"]
            strict(schema)
            path = os.path.join(out_dir, f"{kind}_{version['name']}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(schema, handle)
            count += 1
    if count == 0:
        sys.exit("aucune CRD trouvée sur l'entrée standard")
    print(f"{count} schéma(s) généré(s) dans {out_dir}")


if __name__ == "__main__":
    main()
