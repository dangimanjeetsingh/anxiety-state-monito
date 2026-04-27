from backend.config import load_config
from backend.state_service import AnxietyStateService
import time

cfg = load_config()
print(f"Config: MA_window={cfg.pipeline.moving_average_window}, slide_window={cfg.pipeline.sliding_window_seconds}s")
print(f"Fixed baseline: HR={cfg.baseline.fixed_hr}, GSR={cfg.baseline.fixed_gsr}")

s = AnxietyStateService(cfg)
s.start_reader()

print("\nt    | calib | window | HR      | GSR     | state")
print("-----|-------|--------|---------|---------|------")
for i in range(10):
    time.sleep(2)
    d = s.to_json_dict()
    h = f"{d['hr']:.1f}" if d['hr'] else "None"
    g = f"{d['gsr']:.1f}" if d['gsr'] else "None"
    print(f"{i*2:4}s | {str(d['calibrated']):5} | {str(d['window_samples']):6} | {h:7} | {g:7} | {d['state']}")
