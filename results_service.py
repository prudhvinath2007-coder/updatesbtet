import json
import requests
from typing import Dict, Any, List, Tuple
from requests.exceptions import RequestException # NEW IMPORT

API_URL = "https://www.sbtet.telangana.gov.in/api/api/Results/GetConsolidatedResults"


def fetch_and_parse(pin: str, timeout: int = 20, max_unwrap: int = 5) -> Dict[str, Any]:
    """
    Fetch consolidated results for a PIN and robustly parse double-encoded JSON.
    """
    try:
        resp = requests.get(
            API_URL,
            params={"Pin": pin},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        
        # Raise HTTPError for bad responses (4xx or 5xx)
        resp.raise_for_status() 

        # --- Parsing Logic (Retained) ---
        
        raw_text = resp.text
        data = None
        try:
            data = resp.json()
        except ValueError:
            data = None

        if isinstance(data, str):
            for _ in range(max_unwrap):
                try:
                    data = json.loads(data)
                except Exception:
                    break
                if not isinstance(data, str):
                    break

        if data is None:
            try:
                data = json.loads(raw_text)
            except Exception:
                if raw_text.startswith('"') and raw_text.endswith('"'):
                    inner = json.loads(raw_text)
                    if isinstance(inner, str):
                        data = json.loads(inner)
                    else:
                        data = inner
                else:
                    # Original code used: raise RuntimeError("Response is not valid JSON")
                    # Changed to return {} to avoid crashing the worker process.
                    print(f"API Response is not valid JSON/Data for PIN {pin}")
                    return {}

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass

        if isinstance(data, list):
            return {"Table2": data}
        if not isinstance(data, dict):
            return {}

        return data

    except RequestException as e:
        # Handle connection errors, timeouts, or HTTP status errors gracefully
        print(f"API Request (Network/HTTP) failed for PIN {pin}: {e}")
        return {}
    except Exception as e:
        # Catch unexpected errors during parsing or data handling
        print(f"API Fetch/Parse FAILED UNEXPECTEDLY for PIN {pin}: {e}")
        return {}


def build_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    student = (data.get("Table") or [{}])[0]
    totals = (data.get("Table1") or [{}])[0]
    return {
        "pin": student.get("Pin", ""),
        "student_name": student.get("StudentName", ""),
        "branch_code": student.get("BranchCode", "") or student.get("Branch_Code", ""),
        "scheme": student.get("Scheme", ""),
        "center_code": student.get("CenterCode", ""),
        "center_name": student.get("CenterName", ""),
        "total_max_credits": totals.get("TotalMaxCredits", ""),
        "credits_gained": totals.get("CreditsGained", ""),
        "cgpa_total_gained": totals.get("CgpaTotalGained", ""),
        "cgpa_total_credits": totals.get("CgpaTotalCredits", ""),
        "cgpa": totals.get("CGPA", ""),
    }


def compute_sgpa_by_sem(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    sem_rows = data.get("Table3") or []
    result = []

    for row in sem_rows:
        total_gp = row.get("TotalGradePoints") or 0
        credits = row.get("Credits") or 0
        sgpa = row.get("SGPA")
        if not sgpa and credits:
            sgpa = round(float(total_gp) / float(credits), 2)
        result.append(
            {
                "sem_id": row.get("SemId"),
                "semester": row.get("Semester"),
                "total_grade_points": total_gp,
                "credits": credits,
                "sgpa": sgpa,
            }
        )
    return result


def classify_subject_type(subj: Dict[str, Any]) -> str:
    name = (subj.get("SubjectName") or "").lower()
    max_credits = float(subj.get("MaxCredits") or 0)

    if "lab" in name or "drawing" in name or max_credits <= 1.5:
        return "Lab"
    return "Theory"


def build_subject_insights(subjects: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not subjects:
        return {}

    # Basic processing
    for s in subjects:
        s["Type"] = classify_subject_type(s)
        s["SubjectTotalNum"] = float(s.get("SubjectTotal") or 0)
        s["GradePointNum"] = float(s.get("GradePoint") or 0)

    # Split by type
    theory = [s for s in subjects if s["Type"] == "Theory"]
    labs = [s for s in subjects if s["Type"] == "Lab"]

    def best_and_worst(subj_list: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not subj_list:
            return None, None
        best = max(subj_list, key=lambda x: x["SubjectTotalNum"])
        worst = min(subj_list, key=lambda x: x["SubjectTotalNum"])
        return best, worst

    best_theory, worst_theory = best_and_worst(theory)
    best_lab, worst_lab = best_and_worst(labs)

    # Grade distribution
    grade_counts = {}
    for s in subjects:
        g = s.get("HybridGrade") or "NA"
        grade_counts[g] = grade_counts.get(g, 0) + 1

    # Weak subjects (GradePoint < 9 or marks < 75)
    weak_subjects = [
        s for s in subjects
        if s["GradePointNum"] < 9 or s["SubjectTotalNum"] < 75
    ]
    weak_subjects_sorted = sorted(
        weak_subjects,
        key=lambda x: (x["GradePointNum"], x["SubjectTotalNum"])
    )

    # Per-semester averages
    sem_map: Dict[str, Dict[str, Any]] = {}
    for s in subjects:
        sem = s.get("Semester") or "NA"
        if sem not in sem_map:
            sem_map[sem] = {"total": 0.0, "count": 0}
        sem_map[sem]["total"] += s["SubjectTotalNum"]
        sem_map[sem]["count"] += 1

    sem_averages = []
    for sem, v in sorted(sem_map.items()):
        avg = round(v["total"] / v["count"], 2) if v["count"] else 0
        sem_averages.append(
            {"semester": sem, "avg_marks": avg, "subjects": v["count"]}
        )

    # Top 5 subjects overall
    top_subjects = sorted(
        subjects, key=lambda x: x["SubjectTotalNum"], reverse=True
    )[:5]

    return {
        "best_theory": best_theory,
        "worst_theory": worst_theory,
        "best_lab": best_lab,
        "worst_lab": worst_lab,
        "grade_counts": grade_counts,
        "weak_subjects": weak_subjects_sorted,
        "sem_averages": sem_averages,
        "top_subjects": top_subjects,
    }


def prepare_result_context(pin: str) -> Dict[str, Any]:
    """
    Fetch data and prepare everything needed by templates.
    """
    data = fetch_and_parse(pin)
    
    if not data:
        # If fetching or parsing failed, return an empty summary
        return {"summary": {}}

    subjects = data.get("Table2") or []

    summary = build_summary(data)
    sgpa_info = compute_sgpa_by_sem(data)
    insights = build_subject_insights(subjects)

    context = {
        "summary": summary,
        "subjects": subjects,
        "sgpa_info": sgpa_info,
        "insights": insights,
    }
    return context