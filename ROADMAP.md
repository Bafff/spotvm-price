# spotvm-tool Roadmap

## 🎯 Current Status (v0.2.0-dev)

### ✅ Implemented Features
- Azure Spot VM placement score analysis
- Historical price and eviction rate data from Resource Graph
- Performance comparison with configurable baseline SKU
- JSON and ASCII table output formats
- Intelligent ranking (Placement > Eviction > Price/Performance)
- Availability zone support
- Caching with TTL
- Emoji status indicators (✅❌❓)
- Comprehensive documentation
- **NEW:** Historical data tracking with `--save-results`
- **NEW:** Trend analysis with `--analyze-history`
- **NEW:** CSV export for visualization (history.csv)

---

## 🚀 Planned Improvements

### Phase 1: Essential Filters & Export (v0.2.0)
**Timeline:** 2-3 hours development
**Priority:** 🔥 HIGH

#### 1.1 Cost Filtering
```bash
--max-price <float>           # Maximum price per hour (USD)
--max-eviction <float>        # Maximum eviction rate (%)
--min-performance <float>     # Minimum performance vs baseline (%)
```

**Impact:** Immediately useful for budget-constrained scenarios
**Complexity:** ⭐ Easy (30 min)

#### 1.2 CSV Export
```bash
--csv <file>                  # Export to CSV for Excel/Google Sheets
```

**Impact:** Essential for non-technical stakeholders
**Complexity:** ⭐ Easy (20 min)

#### 1.3 Cost Calculator
```
Monthly cost estimate: $24.53 (730 hrs × $0.0336/hr)
Savings vs on-demand: 72%
```

**Impact:** Shows real business value
**Complexity:** ⭐⭐ Medium (30 min + API integration)

---

### Phase 2: Smart Automation (v0.3.0)
**Timeline:** 4-6 hours development
**Priority:** 🎯 MEDIUM

#### 2.1 Requirements-Based Matching
```bash
--min-vcpu <int>              # Minimum vCPUs required
--min-ram <int>               # Minimum RAM (GB) required
--auto-select                 # Auto-select SKUs matching requirements
```

**Impact:** Simplifies VM selection process
**Complexity:** ⭐⭐ Medium (45 min)

#### 2.2 Historical Price Trends ✅ IMPLEMENTED
```bash
--save-results                # Save run snapshots to results/runs/
--analyze-history             # Generate unified CSV from past runs
--history-depth <int>         # Limit analysis to N recent runs
--history-output <path>       # Custom CSV output location
```

**Status:** ✅ Completed in v0.2.0
**Impact:** Track price/eviction trends over time, visualize with external tools
**Complexity:** ⭐⭐ Medium (1 hour) - DONE

#### 2.3 Watch Mode
```bash
--watch                       # Continuously monitor and alert on changes
--alert-on-drop <percent>     # Alert when price drops by %
```

**Impact:** Catch price drops in real-time
**Complexity:** ⭐⭐⭐ Complex (2 hours)

---

### Phase 3: Visual & Reporting (v0.4.0)
**Timeline:** 6-8 hours development
**Priority:** 🟢 LOW-MEDIUM

#### 3.1 Visual Charts
- ASCII histograms for price distribution
- Matplotlib/Plotly charts (--chart option)
- Heat map of regions by price/eviction

**Complexity:** ⭐⭐⭐ Complex (3 hours)

#### 3.2 HTML Report
```bash
--html <file>                 # Generate interactive HTML report
```

**Impact:** Professional reports for management
**Complexity:** ⭐⭐⭐ Complex (2 hours)

#### 3.3 Colored Terminal Output
- Red for high eviction (>15%)
- Yellow for medium (5-15%)
- Green for low (<5%)

**Complexity:** ⭐ Easy (30 min)

---

### Phase 4: Infrastructure Integration (v0.5.0)
**Timeline:** 8-12 hours development
**Priority:** 🟢 LOW

#### 4.1 Terraform Export
```bash
--terraform <file>            # Export to Terraform format
```

```hcl
resource "azurerm_linux_virtual_machine" "spot" {
  name                = "spot-vm"
  location            = "centralus"
  size                = "Standard_D4as_v5"
  priority            = "Spot"
  eviction_policy     = "Deallocate"
  max_bid_price       = 0.0336
  # ...
}
```

**Impact:** Seamless IaC integration
**Complexity:** ⭐⭐⭐ Complex (3 hours)

#### 4.2 Existing VM Monitoring
```bash
--monitor-existing            # Check existing Spot VMs in subscription
--alert-on-eviction          # Notify before eviction
```

**Impact:** Proactive eviction management
**Complexity:** ⭐⭐⭐⭐ Very Complex (4 hours)

#### 4.3 Cost Optimization Recommendations
```
💡 Cost Savings Opportunities:
- Switch Standard_E4s_v5 → Standard_D4as_v5: Save $0.0217/hr (39%)
- Consider Reserved Instances for predictable workloads: Save 65%
- Schedule VM: Run 8am-6pm weekdays only: Save $7.15/month
```

**Impact:** Actionable cost reduction advice
**Complexity:** ⭐⭐⭐ Complex (2 hours)

---

### Phase 5: Advanced Features (v0.6.0+)
**Timeline:** 20+ hours development
**Priority:** 💡 NICE TO HAVE

#### 5.1 Multi-Cloud Support
- AWS EC2 Spot Instances comparison
- GCP Preemptible VMs comparison
- Unified ranking across clouds

**Complexity:** ⭐⭐⭐⭐⭐ Very Complex

#### 5.2 Machine Learning Predictions
- Eviction rate forecasting (ML model)
- Price trend predictions
- Optimal replacement timing

**Complexity:** ⭐⭐⭐⭐⭐ Very Complex

#### 5.3 Webhook Notifications
```bash
--webhook-slack <url>         # Slack webhook for alerts
--webhook-teams <url>         # Microsoft Teams webhook
--webhook-discord <url>       # Discord webhook
```

**Complexity:** ⭐⭐ Medium

#### 5.4 Grafana/Prometheus Integration
- Metrics exporter
- Grafana dashboard templates
- Real-time monitoring

**Complexity:** ⭐⭐⭐⭐ Very Complex

---

## 🎯 Recommended Next Steps

### Immediate (Next Sprint)
1. **Cost Filtering** - High business value, low complexity
2. **CSV Export** - Frequently requested, easy to implement
3. **Monthly Cost Calculator** - Demonstrates ROI

### Short Term (Next Month)
4. **Requirements Matching** - Better UX
5. **Historical Trends** - Better decision making
6. **Colored Output** - Visual improvement

### Medium Term (Next Quarter)
7. **HTML Reports** - Professional presentation
8. **Terraform Export** - IaC workflow integration
9. **Watch Mode** - Real-time monitoring

### Long Term (Future)
10. **Multi-cloud** - Competitive analysis
11. **ML Predictions** - Advanced intelligence
12. **Monitoring Dashboard** - Enterprise features

---

## 📊 Feature Priority Matrix

```
  High Business Value
         ↑
    1,2,3│7,8
         │
    4,5  │9
  ───────┼─────────→
    6,10 │11,12    High Complexity
         │
  Low Business Value
```

**Legend:**
- **Quadrant 1 (High Value, Low Complexity):** Quick wins ⭐⭐⭐⭐⭐
- **Quadrant 2 (High Value, High Complexity):** Strategic investments ⭐⭐⭐⭐
- **Quadrant 3 (Low Value, Low Complexity):** Nice-to-haves ⭐⭐⭐
- **Quadrant 4 (Low Value, High Complexity):** Avoid/defer ⭐

---

## 🤝 Contributing

Interested in implementing any of these features? Check our [CONTRIBUTING.md](CONTRIBUTING.md) guide!

### Easy First Issues
- Colored terminal output
- CSV export
- Cost filtering
- Progress indicators

### Good Second Issues
- Requirements matching
- HTML reports
- Historical price trends

### Advanced Features
- Terraform export
- ML predictions
- Multi-cloud support

---

## 📝 Version History

- **v0.1.0** (Current) - Initial release with core functionality
- **v0.2.0** (Planned) - Cost filtering, CSV export, cost calculator
- **v0.3.0** (Planned) - Smart automation and historical analysis
- **v0.4.0** (Planned) - Visual charts and reporting
- **v0.5.0** (Planned) - Infrastructure integration
- **v0.6.0+** (Future) - Advanced features and ML

---

## 💬 Feedback

Have suggestions? Open an issue on GitHub or contribute directly!
