# OsteoTwin — GCP Spot Instance Cost Estimation for SOFA/FEA Workloads

> Phase 5: Soft-tissue biomechanics on cloud GPU Spot instances

## Why Cloud for Phase 5?

SOFA Framework FEA simulations require:
- **64-128 GB RAM** for large mesh deformation (local homelab has 16 GB)
- **GPU acceleration** for position-based dynamics (local RTX 3060 has 8 GB VRAM)
- **Burst compute** — simulations run for 5-30 minutes per case, not 24/7

Spot/Preemptible VMs are 60-91% cheaper than on-demand, and our checkpoint/failover worker handles preemption gracefully.

## Instance Options

### Option A: NVIDIA T4 Spot (Budget — Good for Phase 5 MVP)

| Component | Spec | Spot Price/hr |
|-----------|------|---------------|
| Machine | `n1-standard-8` (8 vCPU, 30 GB RAM) | ~$0.04 |
| GPU | NVIDIA T4 (16 GB VRAM) | ~$0.11 |
| Disk | 100 GB pd-ssd | ~$0.02 |
| **Total** | | **~$0.17/hr** |

- **Per simulation (15 min avg):** ~$0.04
- **Per case (3 plans × 2 simulations):** ~$0.25
- **Monthly (20 cases/month):** ~$5.00

### Option B: NVIDIA L4 Spot (Recommended — Best price/performance)

| Component | Spec | Spot Price/hr |
|-----------|------|---------------|
| Machine | `g2-standard-8` (8 vCPU, 32 GB RAM) | ~$0.12 |
| GPU | NVIDIA L4 (24 GB VRAM) | ~$0.17 |
| Disk | 100 GB pd-ssd | ~$0.02 |
| **Total** | | **~$0.31/hr** |

- **Per simulation (10 min avg, faster GPU):** ~$0.05
- **Per case (3 plans × 2 simulations):** ~$0.30
- **Monthly (20 cases/month):** ~$6.00

### Option C: NVIDIA A100 Spot (Premium — Complex multi-body FEA)

| Component | Spec | Spot Price/hr |
|-----------|------|---------------|
| Machine | `a2-highgpu-1g` (12 vCPU, 85 GB RAM) | ~$0.56 |
| GPU | NVIDIA A100 40GB | ~$0.78 |
| Disk | 100 GB pd-ssd | ~$0.02 |
| **Total** | | **~$1.36/hr** |

- **Per simulation (5 min avg):** ~$0.11
- **Per case (3 plans × 2 simulations):** ~$0.67
- **Monthly (20 cases/month):** ~$13.40

### Option D: High-RAM CPU Only (SOFA without GPU acceleration)

| Component | Spec | Spot Price/hr |
|-----------|------|---------------|
| Machine | `n2-highmem-8` (8 vCPU, 64 GB RAM) | ~$0.10 |
| Disk | 100 GB pd-ssd | ~$0.02 |
| **Total** | | **~$0.12/hr** |

- **Per simulation (30 min avg, CPU only):** ~$0.06
- **Per case:** ~$0.36
- **Monthly:** ~$7.20

## Recommendation

**Start with Option A (T4 Spot) at ~$0.17/hr.**

Reasons:
1. T4 has 16 GB VRAM — sufficient for single-bone FEA meshes (< 500K elements)
2. 30 GB system RAM handles SOFA's in-memory deformation state
3. At $0.04 per simulation, even aggressive testing costs < $5/month
4. If T4 is too slow, upgrade to L4 (Option B) by changing one line in Terraform

## Cost Controls

### Already Implemented
- MIG `target_size = 0` — zero cost until explicitly activated
- Worker ACK-on-complete — no wasted compute on failed simulations
- Checkpoint/failover — preempted work resumes, not restarted

### Additional Safeguards to Add
```hcl
# Budget alert in Terraform
resource "google_billing_budget" "compute" {
  billing_account = var.billing_account
  display_name    = "OsteoTwin Compute Budget"
  amount {
    specified_amount {
      currency_code = "USD"
      units         = "50"  # $50/month hard cap
    }
  }
  threshold_rules {
    threshold_percent = 0.5  # alert at $25
  }
  threshold_rules {
    threshold_percent = 0.9  # alert at $45
  }
}
```

## Activation Procedure

```bash
# 1. Update Terraform with GPU accelerator for your target zone
# 2. Set target_size = 1 (or more for parallel simulations)
cd infra/terraform
terraform apply

# 3. Verify worker starts and pulls from Pub/Sub
gcloud compute instances list --project=osteotwin-37f03c

# 4. Submit a simulation via the Planning Server
curl -X POST http://localhost:8200/api/v1/pipeline/simulate/async \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task": {...}, "task_type": "action"}'

# 5. When done, scale back to 0
# Set target_size = 0 in main.tf
terraform apply
```

## Monthly Cost Summary (20 cases/month)

| Option | GPU | Spot $/hr | Monthly Est. | Notes |
|--------|-----|-----------|-------------|-------|
| **A: T4** | 16 GB | $0.17 | **~$5** | Budget pick, Phase 5 MVP |
| **B: L4** | 24 GB | $0.31 | **~$6** | Best value, recommended |
| **C: A100** | 40 GB | $1.36 | **~$13** | Complex multi-body only |
| **D: CPU** | None | $0.12 | **~$7** | SOFA without GPU accel |
| **Local** | RTX 3060 8GB | $0 | **$0** | Phases 1-2 only (16GB RAM limit) |
