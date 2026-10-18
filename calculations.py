"""
calculations.py
----------------
The core calculation engine for the C.G.P.I Calculator.

Design rule: NOTHING in this file talks to Flask, HTML, or the database.
Every function takes plain Python data in (numbers, lists, dicts) and
returns plain Python data out. That's what makes it independently
testable and reusable.

All math is done with Decimal to avoid floating-point rounding errors
(e.g. 0.1 + 0.2 != 0.3 in plain float).
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


# ---------------------------------------------------------------------------
# CONFIG: Grading scheme + rounding policy
# ---------------------------------------------------------------------------
# A single default 10-point grading scheme, expressed as marks ranges.
# This is the ONLY place grading rules live — calculations never
# hard-code a grade or grade point directly.
DEFAULT_GRADING_SCHEME = [
    # (grade_label, min_marks, max_marks, grade_point)
    ("O",  80.00, 100, Decimal("10")),
    ("A+", 75.00, 79.99,  Decimal("9")),
    ("A",  70.00, 74.99,  Decimal("8")),
    ("B+", 60.00, 69.99,  Decimal("7")),
    ("B",  50.00, 59.99,  Decimal("6")),
    ("C",  45.00, 49.99,  Decimal("5")),
    ("D",  40.00, 44.99,  Decimal("4")),
    ("F",  0,  39.99,  Decimal("0")),
]

MAX_GRADE_POINT = max(row[3] for row in DEFAULT_GRADING_SCHEME)  # 10
MIN_GRADE_POINT = min(row[3] for row in DEFAULT_GRADING_SCHEME)  # 0

# Displayed results are rounded to this many decimal places.
# Change this ONE constant if a university uses a different rounding rule.
DISPLAY_DECIMAL_PLACES = Decimal("0.01")   # 2 decimal places

# Internal intermediate math is kept at higher precision than the display
# value, then only rounded at the very last step (when we return a result
# meant for display). This avoids compounding rounding errors across
# multiple calculations.
INTERNAL_DECIMAL_PLACES = Decimal("0.000001")  # 6 decimal places


class ValidationError(Exception):
    """Raised when input data is invalid. Caught by Flask routes and
    turned into a friendly on-screen message -- never a stack trace."""
    pass


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _to_decimal(value, field_name="value"):
    """Safely convert any input (str, int, float) to Decimal.
    Raises ValidationError instead of letting InvalidOperation leak out."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"{field_name} must be a valid number, got: {value!r}")


def _round_display(value):
    """Round a Decimal to the display precision (2 dp by default)."""
    return value.quantize(DISPLAY_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _round_internal(value):
    """Round a Decimal to the internal working precision (6 dp)."""
    return value.quantize(INTERNAL_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# MARKS -> GRADE -> GRADE POINT
# ---------------------------------------------------------------------------

def marks_to_grade(marks, scheme=None):
    """
    Convert numeric marks into (grade_label, grade_point) using the given
    grading scheme (defaults to DEFAULT_GRADING_SCHEME).

    Returns: (grade_label: str, grade_point: Decimal)
    Raises: ValidationError if marks are out of range or invalid.
    """
    scheme = scheme or DEFAULT_GRADING_SCHEME
    marks_dec = _to_decimal(marks, "marks")

    if marks_dec < 0 or marks_dec > 100:
        raise ValidationError(f"Marks must be between 0 and 100, got: {marks}")

    for grade_label, min_marks, max_marks, grade_point in scheme:
        if Decimal(min_marks) <= marks_dec <= Decimal(max_marks):
            return grade_label, grade_point

    # Should not happen if the scheme covers 0-100 fully, but guard anyway.
    raise ValidationError(f"No grade found for marks: {marks}")


def grade_to_point(grade_label, scheme=None):
    """
    Convert a grade label (e.g. 'A+') directly into a grade point,
    without going through marks.
    """
    scheme = scheme or DEFAULT_GRADING_SCHEME
    for label, _min, _max, grade_point in scheme:
        if label.strip().upper() == str(grade_label).strip().upper():
            return grade_point
    raise ValidationError(f"'{grade_label}' is not a valid grade in the current scheme.")


# ---------------------------------------------------------------------------
# SUBJECT VALIDATION
# ---------------------------------------------------------------------------

def validate_subject(subject, seen_names=None):
    """
    Validate a single subject dict of the form:
        {"name": str, "credits": number, "grade": str | None, "marks": number | None}

    Exactly one of "grade" or "marks" must be provided (not both, not neither).
    Returns a cleaned dict: {"name", "credits" (Decimal), "grade" (str), "grade_point" (Decimal)}
    """
    name = (subject.get("name") or "").strip()
    if not name:
        raise ValidationError("Subject name cannot be empty.")

    if seen_names is not None:
        if name.lower() in seen_names:
            raise ValidationError(f"Duplicate subject detected: '{name}'")
        seen_names.add(name.lower())

    credits = _to_decimal(subject.get("credits"), f"Credits for '{name}'")
    if credits <= 0:
        raise ValidationError(f"Credits for '{name}' must be positive, got: {credits}")

    grade = subject.get("grade")
    marks = subject.get("marks")

    if grade and marks is not None:
        raise ValidationError(
            f"'{name}': provide EITHER a grade OR marks, not both."
        )
    if not grade and marks is None:
        raise ValidationError(
            f"'{name}': you must provide a grade or marks."
        )

    if marks is not None:
        grade_label, grade_point = marks_to_grade(marks)
    else:
        grade_label = str(grade).strip().upper()
        grade_point = grade_to_point(grade_label)

    return {
        "name": name,
        "credits": credits,
        "grade": grade_label,
        "grade_point": grade_point,
    }


def validate_subject_list(subjects):
    """
    Validate a full list of subject dicts for one semester.
    Returns a list of cleaned subject dicts (see validate_subject).
    Raises ValidationError if the list is empty or any subject is invalid.
    """
    if not subjects:
        raise ValidationError("A semester must contain at least one subject.")

    seen_names = set()
    cleaned = [validate_subject(s, seen_names) for s in subjects]
    return cleaned


# ---------------------------------------------------------------------------
# SGPI
# ---------------------------------------------------------------------------

def calculate_sgpi(subjects):
    """
    Calculate SGPI for one semester.

    Input: list of subject dicts, e.g.
        [{"name": "Maths", "credits": 4, "grade": "A+"},
         {"name": "Physics", "credits": 3, "marks": 76}]

    Formula: SGPI = Σ(Credit_i × GradePoint_i) / Σ(Credit_i)

    Returns a dict with the full step-by-step breakdown:
        {
            "rows": [ {"name", "credits", "grade", "grade_point", "weighted_points"}, ... ],
            "total_credits": Decimal,
            "total_weighted_points": Decimal,
            "sgpi": Decimal (rounded to display precision)
        }
    """
    cleaned = validate_subject_list(subjects)

    rows = []
    total_credits = Decimal("0")
    total_weighted_points = Decimal("0")

    for subj in cleaned:
        weighted = subj["credits"] * subj["grade_point"]
        rows.append({
            "name": subj["name"],
            "credits": subj["credits"],
            "grade": subj["grade"],
            "grade_point": subj["grade_point"],
            "weighted_points": _round_internal(weighted),
        })
        total_credits += subj["credits"]
        total_weighted_points += weighted

    # Division by zero is structurally impossible here because
    # validate_subject_list guarantees at least one subject with
    # positive credits -- but we guard explicitly anyway, since a
    # calculation engine should never trust its own callers blindly.
    if total_credits == 0:
        raise ValidationError("Total credits cannot be zero.")

    sgpi = total_weighted_points / total_credits

    return {
        "rows": rows,
        "total_credits": total_credits,
        "total_weighted_points": _round_internal(total_weighted_points),
        "sgpi": _round_display(sgpi),
    }


# ---------------------------------------------------------------------------
# CGPI
# ---------------------------------------------------------------------------

def calculate_cgpi(semesters):
    """
    Calculate cumulative CGPI across multiple semesters.

    Input: list of dicts, e.g.
        [{"sgpi": 9.09, "credits": 22}, {"sgpi": 8.5, "credits": 24}]

    Formula: CGPI = Σ(SGPI_sem × Credits_sem) / Σ(Credits_sem)

    This is deliberately NOT a plain average of SGPIs -- semesters with
    more credits should weigh more heavily.

    Returns a dict with breakdown, same shape philosophy as calculate_sgpi.
    """
    if not semesters:
        raise ValidationError("At least one semester is required to calculate CGPI.")

    rows = []
    total_credits = Decimal("0")
    total_weighted_points = Decimal("0")

    for i, sem in enumerate(semesters, start=1):
        sgpi = _to_decimal(sem.get("sgpi"), f"SGPI for semester {i}")
        credits = _to_decimal(sem.get("credits"), f"Credits for semester {i}")

        if credits <= 0:
            raise ValidationError(f"Semester {i}: credits must be positive.")
        if sgpi < MIN_GRADE_POINT or sgpi > MAX_GRADE_POINT:
            raise ValidationError(
                f"Semester {i}: SGPI {sgpi} is outside the valid range "
                f"({MIN_GRADE_POINT}-{MAX_GRADE_POINT})."
            )

        weighted = sgpi * credits
        rows.append({
            "semester": i,
            "sgpi": sgpi,
            "credits": credits,
            "weighted_points": _round_internal(weighted),
        })
        total_credits += credits
        total_weighted_points += weighted

    if total_credits == 0:
        raise ValidationError("Total credits cannot be zero.")

    cgpi = total_weighted_points / total_credits

    return {
        "rows": rows,
        "total_credits": total_credits,
        "total_weighted_points": _round_internal(total_weighted_points),
        "cgpi": _round_display(cgpi),
    }


def calculate_cgpi_from_all_subjects(all_semester_subjects):
    """
    Alternative CGPI calculation: instead of using cached per-semester
    SGPI values, recompute CGPI directly from every subject across every
    semester. Useful as a cross-check that both approaches agree, and as
    the 'source of truth' method described in the project spec.

    Input: list of subject-lists, one list per semester, e.g.
        [ [subj1, subj2, ...],   # semester 1 subjects
          [subj1, subj2, ...] ]  # semester 2 subjects

    Formula: CGPI = Σ(Credit × GradePoint) over ALL subjects, ALL semesters
                     / Σ(Credit) over ALL subjects, ALL semesters
    """
    if not all_semester_subjects:
        raise ValidationError("At least one semester is required to calculate CGPI.")

    total_credits = Decimal("0")
    total_weighted_points = Decimal("0")

    for sem_index, subjects in enumerate(all_semester_subjects, start=1):
        cleaned = validate_subject_list(subjects)
        for subj in cleaned:
            total_credits += subj["credits"]
            total_weighted_points += subj["credits"] * subj["grade_point"]

    if total_credits == 0:
        raise ValidationError("Total credits cannot be zero.")

    cgpi = total_weighted_points / total_credits
    return _round_display(cgpi)


# ---------------------------------------------------------------------------
# EXPECTED CGPI
# ---------------------------------------------------------------------------

def calculate_expected_cgpi(current_cgpi, completed_credits, expected_sgpi, future_credits):
    """
    Estimate future CGPI given a hypothetical future SGPI.

    Formula:
        Expected CGPI = (Current CGPI × Completed Credits + Expected SGPI × Future Credits)
                         / (Completed Credits + Future Credits)

    This is explicitly an ESTIMATE -- callers (Flask routes/templates)
    are responsible for labeling it as such in the UI.
    """
    current_cgpi = _to_decimal(current_cgpi, "Current CGPI")
    completed_credits = _to_decimal(completed_credits, "Completed credits")
    expected_sgpi = _to_decimal(expected_sgpi, "Expected SGPI")
    future_credits = _to_decimal(future_credits, "Future credits")

    if completed_credits < 0 or future_credits <= 0:
        raise ValidationError("Completed credits must be >= 0 and future credits must be > 0.")
    if current_cgpi < MIN_GRADE_POINT or current_cgpi > MAX_GRADE_POINT:
        raise ValidationError(f"Current CGPI must be between {MIN_GRADE_POINT} and {MAX_GRADE_POINT}.")
    if expected_sgpi < MIN_GRADE_POINT or expected_sgpi > MAX_GRADE_POINT:
        raise ValidationError(f"Expected SGPI must be between {MIN_GRADE_POINT} and {MAX_GRADE_POINT}.")

    total_credits = completed_credits + future_credits
    if total_credits == 0:
        raise ValidationError("Total credits cannot be zero.")

    numerator = (current_cgpi * completed_credits) + (expected_sgpi * future_credits)
    expected_cgpi = numerator / total_credits

    return {
        "current_cgpi": current_cgpi,
        "completed_credits": completed_credits,
        "expected_sgpi": expected_sgpi,
        "future_credits": future_credits,
        "numerator": _round_internal(numerator),
        "expected_cgpi": _round_display(expected_cgpi),
    }


def calculate_expected_cgpi_from_subjects(current_cgpi, completed_credits, future_subjects):
    """
    Mode 2 of Expected CGPI: user enters hypothetical future subjects
    instead of a single expected SGPI number.

    Internally this:
        1. Runs future_subjects through calculate_sgpi() to get Expected SGPI
        2. Feeds that into calculate_expected_cgpi()

    This reuses the SAME formula as mode 1 -- no duplicated logic.
    """
    sgpi_result = calculate_sgpi(future_subjects)
    future_credits = sgpi_result["total_credits"]
    expected_sgpi = sgpi_result["sgpi"]

    result = calculate_expected_cgpi(current_cgpi, completed_credits, expected_sgpi, future_credits)
    result["future_subjects_breakdown"] = sgpi_result["rows"]
    return result


# ---------------------------------------------------------------------------
# TARGET CGPI -> REQUIRED SGPI
# ---------------------------------------------------------------------------

def calculate_required_sgpi(current_cgpi, completed_credits, future_credits, target_cgpi):
    """
    Calculate the SGPI required in future semesters to reach a target CGPI.

    Formula:
        Required SGPI = [Target CGPI × (Completed + Future Credits)
                          - Current CGPI × Completed Credits] / Future Credits

    Returns a dict including a feasibility flag/message:
        - "achievable": True/False
        - "message": human-readable explanation if not achievable
    """
    current_cgpi = _to_decimal(current_cgpi, "Current CGPI")
    completed_credits = _to_decimal(completed_credits, "Completed credits")
    future_credits = _to_decimal(future_credits, "Future credits")
    target_cgpi = _to_decimal(target_cgpi, "Target CGPI")

    if completed_credits < 0 or future_credits <= 0:
        raise ValidationError("Completed credits must be >= 0 and future credits must be > 0.")
    if current_cgpi < MIN_GRADE_POINT or current_cgpi > MAX_GRADE_POINT:
        raise ValidationError(f"Current CGPI must be between {MIN_GRADE_POINT} and {MAX_GRADE_POINT}.")
    if target_cgpi < MIN_GRADE_POINT or target_cgpi > MAX_GRADE_POINT:
        raise ValidationError(f"Target CGPI must be between {MIN_GRADE_POINT} and {MAX_GRADE_POINT}.")

    total_credits = completed_credits + future_credits
    numerator = (target_cgpi * total_credits) - (current_cgpi * completed_credits)
    required_sgpi = numerator / future_credits

    result = {
        "current_cgpi": current_cgpi,
        "completed_credits": completed_credits,
        "future_credits": future_credits,
        "target_cgpi": target_cgpi,
        "required_sgpi": _round_display(required_sgpi),
        "achievable": True,
        "message": None,
    }

    if required_sgpi > MAX_GRADE_POINT:
        result["achievable"] = False
        result["message"] = "Target CGPI cannot be achieved within the specified credits."
    elif required_sgpi < MIN_GRADE_POINT:
        result["achievable"] = True
        result["message"] = (
            "Target CGPI is already comfortably achievable "
            "(required SGPI is below the minimum possible grade point)."
        )

    return result
