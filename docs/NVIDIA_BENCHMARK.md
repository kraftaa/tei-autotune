# NVIDIA benchmark on k3

The `k3` cluster has the NVIDIA device plugin installed and healthy. The live
cluster inspection on 2026-11-07 found two `g6.xlarge` nodes, each exposing one
NVIDIA L4 GPU. Both GPUs were allocated to Sparkle AI at the time of inspection.

The `k3-applications` GitOps repository also defines scale-to-zero GPU pools:

| Runner label | Node group | GPU | TEI image |
|---|---|---|---|
| `amd64-4x16-gpu` | `gpu-g5-xlarge` | A10G, 24 GB | `86-1.9` |
| `amd64-4x32-gpu` | `gpu-g6e-xlarge` | L40S, 48 GB | `89-1.9` |
| direct Kubernetes pod | `gpu-g6-xlarge` | L4, 24 GB | `89-1.9` |

The GitHub runner configuration uses Docker-in-Docker without an NVIDIA runtime.
Workflow steps can see the GPU, but containers launched by Docker cannot. Run
the official TEI image as a Kubernetes pod instead.

The image selection follows the official TEI hardware table: A10G uses compute
capability 8.6 and L4/L40S use 8.9.

## Prepare the corpus

Use representative, non-secret production-shaped text with one document per
line. The ConfigMap is created directly in the cluster and is not committed.

```bash
kubectl create namespace tei-autotune-bench

kubectl -n tei-autotune-bench create configmap tei-autotune-corpus \
  --from-file=documents.txt=/absolute/path/to/documents.txt
```

ConfigMaps have a practical size limit near 1 MiB. Sample or shorten a larger
corpus while preserving its language and length distribution.

## Run on an NVIDIA L4

The live `gpu-g6-xlarge` pool uses L4 GPUs. Applying this overlay may cause the
cluster autoscaler to provision another billable node because the existing GPUs
may already be allocated.

```bash
kubectl apply -k deploy/kubernetes/nvidia/overlays/l4
kubectl -n tei-autotune-bench rollout status deployment/tei --timeout=20m
kubectl -n tei-autotune-bench wait --for=condition=complete job/tei-autotune \
  --timeout=90m
```

## Run on an A10G or L40S

Use one overlay at a time:

```bash
# A10G on g5.xlarge
kubectl apply -k deploy/kubernetes/nvidia/overlays/a10g

# L40S on g6e.xlarge
kubectl apply -k deploy/kubernetes/nvidia/overlays/l40s
```

Then wait using the same `rollout status` and `wait` commands above.

## Inspect and retrieve results

Record the actual GPU and TEI environment before interpreting the benchmark:

```bash
kubectl -n tei-autotune-bench get pods -o wide
kubectl -n tei-autotune-bench logs deployment/tei --tail=100
kubectl -n tei-autotune-bench logs job/tei-autotune

pod=$(kubectl -n tei-autotune-bench get pod \
  -l job-name=tei-autotune -o jsonpath='{.items[0].metadata.name}')
kubectl -n tei-autotune-bench cp "$pod:/results" ./nvidia-results
```

Preserve `summary.md`, `summary.json`, the optimization JSON and report, and the
safe-rate JSON, Markdown, and HTML files. Repeat the experiment in a fresh
session before presenting the boundary as stable.

## Cleanup

Copy the results first. The job uses ephemeral storage.

```bash
kubectl delete namespace tei-autotune-bench
```

Deleting the namespace releases the GPU. Node scale-down timing is controlled
by the cluster autoscaler.

