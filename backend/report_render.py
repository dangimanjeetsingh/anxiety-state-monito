"""
Projections of the report dict (PLAN.md section 3.4): a deterministic narrative and a
standalone HTML document.

Stdlib only, no template engine, no model. Every sentence is descriptive: the report
states what was measured, never what it caused (PLAN.md section 6).
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

RELIABILITY_BLURB = {
    "GOOD": "The session produced enough usable signal to describe it in full.",
    "LIMITED": "Read the figures below as provisional.",
    "INSUFFICIENT": "There is too little usable signal to characterise this session.",
    "PARTIAL": "This session is still running, so the figures below are incomplete.",
}


def _fmt_duration(seconds: Optional[float]) -> str:
    """'6 min 14 s' / '42 s'."""
    if seconds is None:
        return "an unknown length of time"
    total = int(round(max(0.0, seconds)))
    if total < 60:
        return "%d s" % total
    return "%d min %02d s" % (total // 60, total % 60)


def _num(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "not available"
    return ("%." + str(digits) + "f") % value


def build_narrative(report: Dict[str, Any]) -> List[str]:
    """Deterministic summary assembled from report fields. Sentences with no data are skipped."""
    try:
        return _narrative_inner(report)
    except Exception as e:  # pragma: no cover - a narrative fault must not lose the report
        LOG.debug("narrative build failed: %s", e)
        return []


def _narrative_inner(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    identity = report.get("identity") or {}
    quality = report.get("quality") or {}
    baseline = report.get("baseline") or {}
    states = report.get("states")
    episodes = report.get("episodes") or []
    warnings = report.get("early_warnings")
    interventions = report.get("interventions") or []
    provenance = report.get("provenance")

    # 1. Identity and duration
    label = identity.get("label") or "Unlabelled session"
    lines.append(
        "Session '%s' ran for %s, of which %s was monitored after calibration."
        % (label, _fmt_duration(identity.get("total_duration_s")),
           _fmt_duration(identity.get("monitored_duration_s")))
    )

    # 2. Baseline
    if baseline.get("method") == "fixed":
        lines.append("A configured (non-personalized) baseline was used.")
    elif baseline.get("completed") and baseline.get("hr") is not None \
            and baseline.get("gsr") is not None:
        lines.append(
            "A personal baseline of HR %s bpm and GSR %s was measured over %s s."
            % (_num(baseline.get("hr")), _num(baseline.get("gsr")),
               _num(baseline.get("calibration_duration_s")))
        )
    else:
        lines.append("The baseline never settled, so no state estimates were produced.")

    # 3. Reliability, before the metrics it qualifies
    grade = quality.get("reliability")
    if grade:
        reasons = quality.get("reliability_reasons") or []
        sentence = "Signal reliability for this session was graded %s" % grade
        sentence += (": %s." % "; ".join(reasons)) if reasons else "."
        blurb = RELIABILITY_BLURB.get(grade)
        lines.append(sentence + ((" " + blurb) if blurb else ""))

    # 4. Time in state
    dominant_pct = None
    if states and states.get("seconds"):
        top_state, top_seconds = max(states["seconds"].items(), key=lambda kv: kv[1])
        dominant_pct = (states.get("pct") or {}).get(top_state)
        lines.append(
            "Most of the monitored window was spent in %s (%s%% of the time, %s)."
            % (top_state, _num(dominant_pct), _fmt_duration(top_seconds))
        )

    # 5. Episodes
    if states is not None:
        if episodes:
            longest = max(episodes, key=lambda e: e.get("duration_s") or 0.0)
            detail = "%s episode lasting %s" % (longest.get("kind"),
                                                _fmt_duration(longest.get("duration_s")))
            if longest.get("peak_hr") is not None:
                detail += ", with a peak HR of %s bpm" % _num(longest.get("peak_hr"))
            if longest.get("max_alert_reached"):
                detail += " and a peak alert level of %s" % longest["max_alert_reached"]
            lines.append(
                "%d stress or anxiety episode%s were detected; the longest was a %s."
                % (len(episodes), "" if len(episodes) == 1 else "s", detail)
            )
        else:
            calm_pct = (states.get("pct") or {}).get("CALM")
            if calm_pct is not None:
                lines.append(
                    "No stress or anxiety episodes were detected; the session remained "
                    "in CALM for %s%% of the monitored window." % _num(calm_pct)
                )
            else:
                lines.append("No stress or anxiety episodes were detected.")

    # 6. Early warnings — a count of what happened, never an accuracy figure
    if warnings:
        lines.append(
            "%d early warning%s issued; %d %s followed by the predicted state within "
            "the forecast window."
            % (warnings.get("issued", 0),
               " was" if warnings.get("issued") == 1 else "s were",
               warnings.get("confirmed", 0),
               "was" if warnings.get("confirmed") == 1 else "were")
        )

    # 7. Interventions — observational only
    if interventions:
        for item in interventions:
            lines.append(_intervention_sentence(item))
    else:
        lines.append("No breathing exercise was performed during this session.")

    # 8. Provenance
    if provenance:
        pct = provenance.get("fusion_source_pct") or {}
        rules_pct = pct.get("rules", 0.0)
        ml_pct = (pct.get("ml", 0.0) or 0.0) + (pct.get("both", 0.0) or 0.0)
        lines.append(
            "%s%% of decisions came from the rule engine, %s%% involved the ML model; "
            "the smoothing and state-machine layers suppressed %d unstable label flips."
            % (_num(rules_pct, 1), _num(ml_pct, 1),
               provenance.get("smoothing_suppressed_flips", 0))
        )

    return lines


def _intervention_sentence(item: Dict[str, Any]) -> str:
    """One observational sentence per intervention. States change, never cause."""
    index = item.get("index")
    start = _fmt_duration(item.get("started_at_rel"))
    duration = _fmt_duration(item.get("actual_duration_s"))
    sentence = "Breathing exercise %s began %s into the monitored window and ran for %s" % (
        index, start, duration)
    completion = item.get("completion")
    if completion == "stopped_early":
        sentence += " (stopped early)"
    elif completion == "aborted_by_session_end":
        sentence += " (still running when the session ended)"
    elif completion is None:
        sentence += " (no planned duration was recorded, so it is not known whether it ran in full)"
    sentence += "."

    change = item.get("hr_change_bpm")
    if change is not None:
        direction = "decreased" if change < 0 else ("increased" if change > 0 else "was unchanged")
        if change == 0:
            sentence += " HR was unchanged across the exercise."
        else:
            sentence += " HR %s %s bpm across the exercise." % (direction, _num(abs(change)))
    state_start = item.get("state_at_start")
    state_end = item.get("state_at_end")
    if state_start and state_end:
        if state_start == state_end:
            sentence += " The estimated state remained %s." % state_end
        else:
            sentence += " The estimated state was %s at the start and %s at the end." % (
                state_start, state_end)
    return sentence


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 20px; background: #f4f5f8; color: #1b2030;
       font: 15px/1.6 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .08em; color: #5a6376;
     margin: 32px 0 10px; }
.sub { color: #5a6376; margin: 0 0 24px; }
.banner { padding: 14px 16px; border-radius: 10px; border: 1px solid #d6dae4;
          background: #fff; margin-bottom: 8px; }
.banner.good { border-color: #4FD1AE; background: #f0fbf7; }
.banner.limited { border-color: #F0A857; background: #fff8ef; }
.banner.insufficient { border-color: #F0625F; background: #fff1f1; }
.banner.partial { border-color: #7C9EF5; background: #f2f5ff; }
.banner strong { display: block; font-size: 16px; margin-bottom: 2px; }
.banner ul { margin: 6px 0 0 18px; padding: 0; }
table { border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #d6dae4;
        border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid #eceef3;
         vertical-align: top; }
th { width: 42%; color: #5a6376; font-weight: 600; }
tr:last-child th, tr:last-child td { border-bottom: 0; }
td.na { color: #8a92a4; font-style: italic; }
ol.narrative { padding-left: 20px; }
ol.narrative li { margin-bottom: 6px; }
.disclaimer { margin-top: 32px; padding: 14px 16px; border-radius: 10px;
              background: #eceef3; color: #3c4353; font-size: 13px; }
.footer { margin-top: 16px; color: #8a92a4; font-size: 12px; }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _cell(value: Any, reason: Optional[str] = None, suffix: str = "") -> str:
    """A table cell; missing values say so and why."""
    if value is None or value == {}:
        why = reason or "not recorded for this session"
        return '<td class="na">not available &mdash; %s</td>' % _esc(why)
    return "<td>%s%s</td>" % (_esc(value), _esc(suffix))


def _rows(pairs: List[tuple]) -> str:
    return "".join("<tr><th>%s</th>%s</tr>" % (_esc(label), cell) for label, cell in pairs)


def render_html(report: Dict[str, Any]) -> str:
    """A single self-contained HTML document: inline CSS, no external assets, no scripts."""
    identity = report.get("identity") or {}
    quality = report.get("quality") or {}
    baseline = report.get("baseline") or {}
    unavailable = report.get("unavailable") or {}
    grade = quality.get("reliability") or "UNKNOWN"

    parts: List[str] = []
    parts.append("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>Saarthi session report &mdash; %s</title>" % _esc(identity.get("id")))
    parts.append("<style>%s</style></head><body><div class=\"wrap\">" % _CSS)

    parts.append("<h1>%s</h1>" % _esc(identity.get("label") or "Unlabelled session"))
    parts.append('<p class="sub">Session %s &middot; %s &rarr; %s</p>' % (
        _esc(identity.get("id")), _esc(identity.get("started_at_iso")),
        _esc(identity.get("ended_at_iso"))))

    # Reliability first: it qualifies everything below it.
    reasons = quality.get("reliability_reasons") or []
    banner = ['<div class="banner %s"><strong>Signal reliability: %s</strong>%s'
              % (_esc(grade.lower()), _esc(grade), _esc(RELIABILITY_BLURB.get(grade, "")))]
    if reasons:
        banner.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _esc(r) for r in reasons))
    banner.append("</div>")
    parts.append("".join(banner))

    parts.append("<h2>Session</h2><table>%s</table>" % _rows([
        ("Total duration", _cell(_fmt_duration(identity.get("total_duration_s")))),
        ("Calibration", _cell(_fmt_duration(identity.get("calibration_duration_s")))),
        ("Monitored", _cell(_fmt_duration(identity.get("monitored_duration_s")))),
        ("Ended because", _cell(identity.get("end_reason"))),
        ("State at end", _cell(identity.get("terminal_state"))),
        ("Report status", _cell(report.get("status"))),
    ]))

    parts.append("<h2>Signal quality</h2><table>%s</table>" % _rows([
        ("Samples evaluated", _cell(quality.get("samples_evaluated"))),
        ("Samples rejected", _cell(quality.get("samples_rejected"))),
        ("Expected samples", _cell(quality.get("expected_samples"))),
        ("Coverage", _cell(quality.get("coverage_pct"), suffix="%")),
        ("Mean confidence", _cell(quality.get("mean_confidence"))),
        ("Lowest confidence", _cell(quality.get("min_confidence"))),
        ("Time at low confidence", _cell(quality.get("pct_time_low_confidence"), suffix="%")),
        ("Unstable signal", _cell(quality.get("unstable_signal_pct"), suffix="%")),
        ("Connection gaps", _cell(quality.get("disconnect_count"))),
        ("Total time disconnected", _cell(_fmt_duration(quality.get("total_disconnected_s")))),
    ]))

    parts.append("<h2>Baseline</h2><table>%s</table>" % _rows([
        ("Method", _cell(baseline.get("method"))),
        ("Baseline HR", _cell(baseline.get("hr"), "calibration never completed", " bpm")),
        ("Baseline GSR", _cell(baseline.get("gsr"), "calibration never completed")),
        ("Measured over", _cell(_fmt_duration(baseline.get("calibration_duration_s")))),
        ("Target window", _cell(_fmt_duration(baseline.get("calibration_target_s")))),
        ("Attempts", _cell(baseline.get("calibration_attempts"))),
        ("Completed", _cell(baseline.get("completed"))),
    ]))

    parts.append(_physiology_html(report.get("physiology"), unavailable))
    parts.append(_states_html(report.get("states"), unavailable))
    parts.append(_episodes_html(report.get("episodes"), report.get("episode_count")))
    parts.append(_warnings_html(report.get("early_warnings"), unavailable))
    parts.append(_alerts_html(report.get("alerts"), unavailable))
    parts.append(_interventions_html(report.get("interventions")))
    parts.append(_provenance_html(report.get("provenance"), unavailable))

    narrative = report.get("narrative") or []
    if narrative:
        parts.append("<h2>Summary</h2><ol class=\"narrative\">%s</ol>"
                     % "".join("<li>%s</li>" % _esc(line) for line in narrative))

    parts.append('<p class="disclaimer">%s</p>' % _esc(report.get("disclaimer", "")))
    parts.append('<p class="footer">Generated by Saarthi from session %s.</p>'
                 % _esc(identity.get("id")))
    parts.append("</div></body></html>")
    return "".join(parts)


def _missing_section(title: str, reason: Optional[str]) -> str:
    return '<h2>%s</h2><p class="banner"><span class="na">not available &mdash; %s</span></p>' % (
        _esc(title), _esc(reason or "not recorded for this session"))


def _physiology_html(phys: Optional[Dict[str, Any]], unavailable: Dict[str, str]) -> str:
    if not phys:
        return _missing_section("Physiology", unavailable.get("physiology"))
    hr = phys.get("hr") or {}
    gsr = phys.get("gsr") or {}
    return "<h2>Physiology</h2><table>%s</table>" % _rows([
        ("HR mean / min / max", _cell("%s / %s / %s" % (
            _num(hr.get("mean")), _num(hr.get("min")), _num(hr.get("max"))), suffix=" bpm")),
        ("HR at end", _cell(hr.get("final"), "no valid samples after calibration", " bpm")),
        ("GSR mean / min / max", _cell("%s / %s / %s" % (
            _num(gsr.get("mean")), _num(gsr.get("min")), _num(gsr.get("max"))))),
        ("GSR at end", _cell(gsr.get("final"), "no valid samples after calibration")),
        ("Peak change from baseline", _cell("HR %s bpm / GSR %s" % (
            _num(phys.get("peak_delta_hr")), _num(phys.get("peak_delta_gsr"))))),
        ("Peak stress index", _cell(phys.get("peak_stress_index"))),
        ("Mean stress index", _cell(phys.get("mean_stress_index"))),
        ("Largest deviation at", _cell(
            _fmt_duration(phys.get("peak_deviation_at_rel"))
            if phys.get("peak_deviation_at_rel") is not None else None,
            "no deviation was recorded")),
    ])


def _states_html(states: Optional[Dict[str, Any]], unavailable: Dict[str, str]) -> str:
    if not states:
        return _missing_section("Time in each state", unavailable.get("states"))
    seconds = states.get("seconds") or {}
    pct = states.get("pct") or {}
    rows = [(name, _cell("%s (%s%%)" % (_fmt_duration(value), _num(pct.get(name), 1))))
            for name, value in sorted(seconds.items(), key=lambda kv: -kv[1])]
    rows.append(("State changes", _cell(states.get("transition_count"))))
    return "<h2>Time in each state</h2><table>%s</table>" % _rows(rows)


def _episodes_html(episodes: Optional[List[Dict[str, Any]]], count: Optional[int]) -> str:
    if not episodes:
        return ("<h2>Episodes</h2><p class=\"banner\">No stress or anxiety episodes were "
                "detected during the monitored window.</p>")
    head = ("<tr><th>#</th><th>Kind</th><th>Start</th><th>Duration</th><th>Peak HR</th>"
            "<th>Peak alert</th><th>Ended</th><th>Forecast</th></tr>")
    body = []
    for e in episodes:
        lead = e.get("lead_time_s")
        forecast = ("warned %s s ahead" % _num(lead)) if e.get("preceded_by_early_warning") \
            else "no prior warning"
        body.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td></tr>" % (
                _esc(e.get("index")), _esc(e.get("kind")),
                _esc(_fmt_duration(e.get("start_rel"))), _esc(_fmt_duration(e.get("duration_s"))),
                _esc(_num(e.get("peak_hr"))), _esc(e.get("max_alert_reached") or "none"),
                _esc(e.get("resolved_via") or "escalated"), _esc(forecast)))
    return "<h2>Episodes (%s)</h2><table>%s%s</table>" % (
        _esc(count if count is not None else len(episodes)), head, "".join(body))


def _warnings_html(warnings: Optional[Dict[str, Any]], unavailable: Dict[str, str]) -> str:
    if not warnings:
        return _missing_section("Early warnings", unavailable.get("early_warnings"))
    return "<h2>Early warnings</h2><table>%s</table>" % _rows([
        ("Issued", _cell(warnings.get("issued"))),
        ("Followed by the predicted state", _cell(warnings.get("confirmed"))),
        ("Not followed", _cell(warnings.get("unconfirmed"))),
        ("Median lead time", _cell(warnings.get("median_lead_time_s"),
                                   "no warning was followed by the predicted state", " s")),
    ])


def _alerts_html(alerts: Optional[Dict[str, Any]], unavailable: Dict[str, str]) -> str:
    if not alerts:
        return _missing_section("Alerts", unavailable.get("alerts"))
    counts = alerts.get("counts") or {}
    return "<h2>Alerts</h2><table>%s</table>" % _rows([
        ("Low / medium / high", _cell("%s / %s / %s" % (
            counts.get("LOW", 0), counts.get("MEDIUM", 0), counts.get("HIGH", 0)))),
        ("Peak alert", _cell(alerts.get("peak_alert"), "no alert was raised")),
        ("Time at high", _cell(_fmt_duration(alerts.get("seconds_at_high")))),
    ])


def _interventions_html(interventions: Optional[List[Dict[str, Any]]]) -> str:
    if not interventions:
        return ("<h2>Breathing exercises</h2><p class=\"banner\">No breathing exercise was "
                "performed during this session.</p>")
    blocks = []
    for item in interventions:
        blocks.append("<table>%s</table>" % _rows([
            ("Technique", _cell(item.get("technique"))),
            ("Started", _cell(_fmt_duration(item.get("started_at_rel")))),
            ("Planned / actual", _cell("%s / %s" % (
                _fmt_duration(item.get("planned_duration_s")),
                _fmt_duration(item.get("actual_duration_s"))))),
            ("Completion", _cell(item.get("completion"),
                                  "no planned duration was recorded for this exercise")),
            ("Cycles completed", _cell(item.get("cycles_completed"))),
            ("State at start / end", _cell(
                "%s / %s" % (item.get("state_at_start"), item.get("state_at_end"))
                if item.get("state_at_start") else None,
                "state was not recorded for this exercise")),
            ("HR change across exercise", _cell(item.get("hr_change_bpm"),
                                                "HR was not recorded for this exercise", " bpm")),
            ("Recovery data", _cell(item.get("recovery_data"))),
        ]))
    return "<h2>Breathing exercises (%d)</h2>%s" % (len(interventions), "".join(blocks))


def _provenance_html(prov: Optional[Dict[str, Any]], unavailable: Dict[str, str]) -> str:
    if not prov:
        return _missing_section("How the estimates were produced", unavailable.get("provenance"))
    pct = prov.get("fusion_source_pct") or {}
    return "<h2>How the estimates were produced</h2><table>%s</table>" % _rows([
        ("Rules only", _cell(pct.get("rules"), "no decisions were recorded", "%")),
        ("ML only", _cell(pct.get("ml"), "the ML model did not contribute", "%")),
        ("Rules and ML agreed", _cell(pct.get("both"), "the ML model did not contribute", "%")),
        ("ML-led ANXIETY decisions", _cell(prov.get("ml_anxiety_adoptions"))),
        ("Rule engine matched the final state", _cell(prov.get("rule_final_agreement_pct"),
                                                      "no decisions were recorded", "%")),
        ("Unstable label flips suppressed", _cell(prov.get("smoothing_suppressed_flips"))),
        ("ML model available", _cell(prov.get("ml_model_available"))),
    ])
