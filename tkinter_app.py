"""
tkinter_app.py
--------------
Desktop GUI for the C.G.P.I Calculator, built with Tkinter.

Same architecture as the Flask version:
    calculations.py -> pure math, untouched
    database.py     -> SQLite persistence, untouched
    tkinter_app.py  -> the "view + controller" layer (this file replaces
                        app.py + templates/ + static/ from the web version)

Run with:
    python3 tkinter_app.py
"""

import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import calculations as calc
import database as db


# ---------------------------------------------------------------------------
# Reusable widget: a dynamic list of subject rows (name / credits / grade
# or marks). Used on the SGPI tab and on the "future subjects" mode of the
# Expected CGPI tab -- mirrors the subject_name[]/credits[]/... form arrays
# from the Flask templates.
# ---------------------------------------------------------------------------

class SubjectRows(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []  # list of dicts holding the widgets for one row

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 2))
        for text, width in [("Subject", 22), ("Credits", 8), ("Type", 8), ("Grade / Marks", 14)]:
            ttk.Label(header, text=text, font=("", 9, "bold"), width=width).pack(side="left", padx=2)

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.pack(fill="x")

        ttk.Button(self, text="+ Add subject", command=self.add_row).pack(anchor="w", pady=(4, 0))

        self.add_row()

    def add_row(self, name="", credits="", input_type="grade", value=""):
        row_frame = ttk.Frame(self.rows_frame)
        row_frame.pack(fill="x", pady=1)

        name_var = tk.StringVar(value=name)
        credits_var = tk.StringVar(value=str(credits) if credits != "" else "")
        type_var = tk.StringVar(value=input_type)
        value_var = tk.StringVar(value=str(value) if value != "" else "")

        ttk.Entry(row_frame, textvariable=name_var, width=22).pack(side="left", padx=2)
        ttk.Entry(row_frame, textvariable=credits_var, width=8).pack(side="left", padx=2)
        type_combo = ttk.Combobox(
            row_frame, textvariable=type_var, values=["grade", "marks"],
            width=6, state="readonly"
        )
        type_combo.pack(side="left", padx=2)
        ttk.Entry(row_frame, textvariable=value_var, width=14).pack(side="left", padx=2)

        remove_btn = ttk.Button(row_frame, text="✕", width=3,
                                 command=lambda: self.remove_row(row))
        remove_btn.pack(side="left", padx=2)

        row = {
            "frame": row_frame, "name": name_var, "credits": credits_var,
            "type": type_var, "value": value_var,
        }
        self.rows.append(row)

    def remove_row(self, row):
        if len(self.rows) == 1:
            # Always keep at least one row visible; just clear it instead
            row["name"].set("")
            row["credits"].set("")
            row["value"].set("")
            return
        row["frame"].destroy()
        self.rows.remove(row)

    def clear(self):
        for row in list(self.rows):
            row["frame"].destroy()
        self.rows = []
        self.add_row()

    def load_subjects(self, subjects):
        """Populate rows from a list of cleaned subject dicts (as stored in
        the database: {"name", "credits", "grade", "grade_point"})."""
        for row in list(self.rows):
            row["frame"].destroy()
        self.rows = []
        if not subjects:
            self.add_row()
            return
        for subj in subjects:
            self.add_row(
                name=subj.get("name", ""),
                credits=subj.get("credits", ""),
                input_type="grade",
                value=subj.get("grade", ""),
            )

    def get_subjects(self):
        """Same conversion _subjects_from_form() did in app.py: turn the
        widget rows into the list-of-dicts shape calculations.py expects."""
        subjects = []
        for row in self.rows:
            name = row["name"].get()
            credits = row["credits"].get()
            input_type = row["type"].get()
            value = row["value"].get()
            if not name.strip() and not credits.strip():
                continue
            subject = {"name": name, "credits": credits}
            if input_type == "marks":
                subject["marks"] = value
            else:
                subject["grade"] = value
            subjects.append(subject)
        return subjects


# ---------------------------------------------------------------------------
# Reusable widget: a small results table (Treeview) for showing a
# step-by-step breakdown, e.g. per-subject or per-semester weighted points.
# ---------------------------------------------------------------------------

class BreakdownTable(ttk.Treeview):
    def __init__(self, parent, columns):
        super().__init__(parent, columns=columns, show="headings", height=8)
        for col in columns:
            self.heading(col, text=col)
            self.column(col, width=110, anchor="center")

    def load_rows(self, rows):
        self.delete(*self.get_children())
        for row in rows:
            self.insert("", "end", values=row)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class CGPIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("C.G.P.I Calculator")
        self.geometry("780x600")
        self.minsize(700, 520)

        self.editing_semester_id = None  # None = "add new", else "editing this id"

        db.init_db()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.notebook = notebook

        self.dashboard_tab = ttk.Frame(notebook)
        self.sgpi_tab = ttk.Frame(notebook)
        self.cgpi_tab = ttk.Frame(notebook)
        self.expected_tab = ttk.Frame(notebook)
        self.target_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)

        notebook.add(self.dashboard_tab, text="Dashboard")
        notebook.add(self.sgpi_tab, text="SGPI Calculator")
        notebook.add(self.cgpi_tab, text="CGPI")
        notebook.add(self.expected_tab, text="Expected CGPI")
        notebook.add(self.target_tab, text="Target CGPI")
        notebook.add(self.history_tab, text="History")

        self._build_dashboard_tab()
        self._build_sgpi_tab()
        self._build_cgpi_tab()
        self._build_expected_tab()
        self._build_target_tab()
        self._build_history_tab()

        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.refresh_dashboard()

    # -- tab switching -----------------------------------------------------

    def _on_tab_changed(self, event):
        current = self.notebook.select()
        widget = self.nametowidget(current)
        if widget is self.dashboard_tab:
            self.refresh_dashboard()
        elif widget is self.cgpi_tab:
            self.refresh_cgpi()
        elif widget is self.history_tab:
            self.refresh_history()

    # =======================================================================
    # DASHBOARD
    # =======================================================================

    def _build_dashboard_tab(self):
        frame = self.dashboard_tab
        ttk.Label(frame, text="Dashboard", font=("", 14, "bold")).pack(anchor="w", pady=(4, 8))

        summary = ttk.Frame(frame)
        summary.pack(fill="x", pady=4)
        self.dash_latest_sgpi = ttk.Label(summary, text="Latest SGPI: --", font=("", 11))
        self.dash_latest_sgpi.pack(anchor="w")
        self.dash_cgpi = ttk.Label(summary, text="Overall CGPI: --", font=("", 11, "bold"))
        self.dash_cgpi.pack(anchor="w")

        ttk.Label(frame, text="Semesters on record:", font=("", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.dash_table = BreakdownTable(frame, ("Semester", "SGPI", "Total Credits"))
        self.dash_table.pack(fill="both", expand=True)

    def refresh_dashboard(self):
        semesters = db.get_all_semesters()
        rows = [(s["semester_number"], s["sgpi"], s["total_credits"]) for s in semesters]
        self.dash_table.load_rows(rows)

        if semesters:
            self.dash_latest_sgpi.config(text=f"Latest SGPI: {semesters[-1]['sgpi']}")
            try:
                result = calc.calculate_cgpi(
                    [{"sgpi": s["sgpi"], "credits": s["total_credits"]} for s in semesters]
                )
                self.dash_cgpi.config(text=f"Overall CGPI: {result['cgpi']}")
            except calc.ValidationError as e:
                self.dash_cgpi.config(text="Overall CGPI: --")
                messagebox.showerror("Validation error", str(e))
        else:
            self.dash_latest_sgpi.config(text="Latest SGPI: -- (no semesters saved yet)")
            self.dash_cgpi.config(text="Overall CGPI: --")

    # =======================================================================
    # SGPI CALCULATOR (add / edit semester)
    # =======================================================================

    def _build_sgpi_tab(self):
        frame = self.sgpi_tab
        ttk.Label(frame, text="SGPI Calculator", font=("", 14, "bold")).pack(anchor="w", pady=(4, 8))

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Semester number:").pack(side="left")
        self.sgpi_semester_number = tk.StringVar()
        ttk.Entry(top, textvariable=self.sgpi_semester_number, width=8).pack(side="left", padx=6)
        ttk.Button(top, text="Import CSV...", command=self.import_csv).pack(side="left", padx=12)
        self.sgpi_editing_label = ttk.Label(top, text="", foreground="#555")
        self.sgpi_editing_label.pack(side="left", padx=12)

        self.sgpi_rows = SubjectRows(frame)
        self.sgpi_rows.pack(fill="x", pady=8)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Calculate", command=self.calculate_sgpi).pack(side="left")
        self.sgpi_save_btn = ttk.Button(btns, text="Calculate & Save", command=self.save_sgpi)
        self.sgpi_save_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="New / Clear", command=self.reset_sgpi_form).pack(side="left")

        ttk.Label(frame, text="Breakdown:", font=("", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.sgpi_table = BreakdownTable(
            frame, ("Subject", "Credits", "Grade", "Grade Point", "Weighted Points")
        )
        self.sgpi_table.pack(fill="both", expand=True)

        self.sgpi_result_label = ttk.Label(frame, text="", font=("", 11, "bold"))
        self.sgpi_result_label.pack(anchor="w", pady=6)

    def reset_sgpi_form(self):
        self.editing_semester_id = None
        self.sgpi_semester_number.set("")
        self.sgpi_rows.clear()
        self.sgpi_table.load_rows([])
        self.sgpi_result_label.config(text="")
        self.sgpi_editing_label.config(text="")

    def load_semester_into_sgpi_form(self, semester):
        self.editing_semester_id = semester["id"]
        self.sgpi_semester_number.set(str(semester["semester_number"]))
        self.sgpi_rows.load_subjects(semester["subjects"])
        self.sgpi_table.load_rows([])
        self.sgpi_result_label.config(text="")
        self.sgpi_editing_label.config(text=f"(editing semester #{semester['semester_number']})")
        self.notebook.select(self.sgpi_tab)

    def _run_sgpi_calculation(self):
        subjects_input = self.sgpi_rows.get_subjects()
        result = calc.calculate_sgpi(subjects_input)  # raises ValidationError on bad input
        rows = [
            (r["name"], r["credits"], r["grade"], r["grade_point"], r["weighted_points"])
            for r in result["rows"]
        ]
        self.sgpi_table.load_rows(rows)
        self.sgpi_result_label.config(
            text=f"SGPI = {result['sgpi']}   (Total credits: {result['total_credits']})"
        )
        return result

    def calculate_sgpi(self):
        try:
            self._run_sgpi_calculation()
        except calc.ValidationError as e:
            messagebox.showerror("Validation error", str(e))

    def save_sgpi(self):
        semester_number_raw = self.sgpi_semester_number.get()
        try:
            semester_number = int(semester_number_raw)
        except ValueError:
            messagebox.showerror("Validation error", "Semester number must be a whole number.")
            return

        try:
            result = self._run_sgpi_calculation()
        except calc.ValidationError as e:
            messagebox.showerror("Validation error", str(e))
            return

        db.save_semester(
            semester_number=semester_number,
            subjects=result["rows"],
            total_credits=result["total_credits"],
            sgpi=result["sgpi"],
            semester_id=self.editing_semester_id,
        )
        messagebox.showinfo("Saved", f"Semester {semester_number} saved. SGPI = {result['sgpi']}")
        self.reset_sgpi_form()
        self.refresh_dashboard()
        self.refresh_history()
        self.notebook.select(self.history_tab)

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                subjects = []
                for row in reader:
                    subjects.append({
                        "name": row.get("Subject", ""),
                        "credits": row.get("Credits", ""),
                        "grade": row.get("Grade", ""),
                    })
        except Exception:
            messagebox.showerror("Import failed", "Could not read that CSV file. Check it matches the expected format.")
            return

        try:
            result = calc.calculate_sgpi(subjects)
        except calc.ValidationError as e:
            messagebox.showerror("CSV import failed validation", str(e))
            return

        self.sgpi_rows.load_subjects(result["rows"])
        messagebox.showinfo(
            "Imported",
            f"CSV imported: {len(subjects)} subjects, SGPI = {result['sgpi']}. Review and save below.",
        )

    # =======================================================================
    # CGPI
    # =======================================================================

    def _build_cgpi_tab(self):
        frame = self.cgpi_tab
        ttk.Label(frame, text="CGPI (calculated from all saved semesters)",
                  font=("", 14, "bold")).pack(anchor="w", pady=(4, 8))

        ttk.Button(frame, text="Recalculate", command=self.refresh_cgpi).pack(anchor="w")

        ttk.Label(frame, text="Per-semester breakdown:", font=("", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.cgpi_table = BreakdownTable(frame, ("Semester", "SGPI", "Credits", "Weighted Points"))
        self.cgpi_table.pack(fill="both", expand=True)

        self.cgpi_result_label = ttk.Label(frame, text="", font=("", 11, "bold"))
        self.cgpi_result_label.pack(anchor="w", pady=6)
        self.cgpi_crosscheck_label = ttk.Label(frame, text="", foreground="#555")
        self.cgpi_crosscheck_label.pack(anchor="w")

    def refresh_cgpi(self):
        semesters = db.get_all_semesters()
        self.cgpi_table.load_rows([])
        self.cgpi_result_label.config(text="")
        self.cgpi_crosscheck_label.config(text="")

        if not semesters:
            self.cgpi_result_label.config(text="No semesters saved yet.")
            return

        try:
            result = calc.calculate_cgpi(
                [{"sgpi": s["sgpi"], "credits": s["total_credits"]} for s in semesters]
            )
            rows = [(r["semester"], r["sgpi"], r["credits"], r["weighted_points"]) for r in result["rows"]]
            self.cgpi_table.load_rows(rows)
            self.cgpi_result_label.config(text=f"CGPI = {result['cgpi']}")

            result_direct = calc.calculate_cgpi_from_all_subjects([s["subjects"] for s in semesters])
            self.cgpi_crosscheck_label.config(
                text=f"Cross-check (recomputed directly from every subject): {result_direct}"
            )
        except calc.ValidationError as e:
            messagebox.showerror("Validation error", str(e))

    # =======================================================================
    # EXPECTED CGPI
    # =======================================================================

    def _build_expected_tab(self):
        frame = self.expected_tab

        ttk.Label(
            frame,
            text="Expected CGPI",
            font=("", 14, "bold")
        ).pack(anchor="w", pady=(4, 8))

        common = ttk.Frame(frame)
        common.pack(fill="x")

        self.exp_current_cgpi = tk.StringVar()
        self.exp_completed_credits = tk.StringVar()

        ttk.Label(
            common,
            text="Current CGPI:"
        ).grid(row=0, column=0, sticky="w", padx=4, pady=2)

        ttk.Entry(
            common,
            textvariable=self.exp_current_cgpi,
            width=10
        ).grid(row=0, column=1, padx=4)

        ttk.Label(
            common,
            text="Completed credits:"
        ).grid(row=0, column=2, sticky="w", padx=4)

        ttk.Entry(
            common,
            textvariable=self.exp_completed_credits,
            width=10
        ).grid(row=0, column=3, padx=4)

        self.exp_sgpi_frame = ttk.Frame(frame)

        self.exp_expected_sgpi = tk.StringVar()
        self.exp_future_credits = tk.StringVar()

        ttk.Label(
            self.exp_sgpi_frame,
            text="Expected SGPI:"
        ).grid(row=0, column=0, sticky="w", padx=4, pady=6)

        ttk.Entry(
            self.exp_sgpi_frame,
            textvariable=self.exp_expected_sgpi,
            width=10
        ).grid(row=0, column=1, padx=4)

        ttk.Label(
            self.exp_sgpi_frame,
            text="Future credits:"
        ).grid(row=0, column=2, sticky="w", padx=4)

        ttk.Entry(
            self.exp_sgpi_frame,
            textvariable=self.exp_future_credits,
            width=10
        ).grid(row=0, column=3, padx=4)

        self.exp_sgpi_frame.pack(fill="x")

        ttk.Button(
            frame,
            text="Calculate",
            command=self.calculate_expected_cgpi
        ).pack(anchor="w", pady=8)

        self.exp_result_label = ttk.Label(
            frame,
            text="",
            font=("", 11, "bold"),
            wraplength=680,
            justify="left"
        )

        self.exp_result_label.pack(anchor="w")


    def calculate_expected_cgpi(self):
        current_cgpi = self.exp_current_cgpi.get()
        completed_credits = self.exp_completed_credits.get()
        expected_sgpi = self.exp_expected_sgpi.get()
        future_credits = self.exp_future_credits.get()

        try:
            result = calc.calculate_expected_cgpi(
                current_cgpi,
                completed_credits,
                expected_sgpi,
                future_credits
            )

        except calc.ValidationError as e:
            messagebox.showerror(
                "Validation error",
                str(e)
            )
            return

        self.exp_result_label.config(
            text=(
                f"Expected CGPI = {result['expected_cgpi']}\n"
                f"(Current CGPI {result['current_cgpi']} × "
                f"{result['completed_credits']} completed credits + "
                f"Expected SGPI {result['expected_sgpi']} × "
                f"{result['future_credits']} future credits, "
                f"÷ total credits)\n\n"
                "This is an estimate, not a guarantee."
            )
        )

    # =======================================================================
    # TARGET CGPI
    # =======================================================================

    def _build_target_tab(self):
        frame = self.target_tab
        ttk.Label(frame, text="Target CGPI → Required SGPI", font=("", 14, "bold")).pack(anchor="w", pady=(4, 8))

        form = ttk.Frame(frame)
        form.pack(fill="x")
        self.tgt_current_cgpi = tk.StringVar()
        self.tgt_completed_credits = tk.StringVar()
        self.tgt_future_credits = tk.StringVar()
        self.tgt_target_cgpi = tk.StringVar()

        fields = [
            ("Current CGPI:", self.tgt_current_cgpi),
            ("Completed credits:", self.tgt_completed_credits),
            ("Future credits:", self.tgt_future_credits),
            ("Target CGPI:", self.tgt_target_cgpi),
        ]
        for i, (label, var) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=4)
            ttk.Entry(form, textvariable=var, width=12).grid(row=i, column=1, padx=4, pady=4)

        ttk.Button(frame, text="Calculate", command=self.calculate_target_cgpi).pack(anchor="w", pady=8)
        self.tgt_result_label = ttk.Label(frame, text="", font=("", 11, "bold"), wraplength=680, justify="left")
        self.tgt_result_label.pack(anchor="w")

    def calculate_target_cgpi(self):
        try:
            result = calc.calculate_required_sgpi(
                current_cgpi=self.tgt_current_cgpi.get(),
                completed_credits=self.tgt_completed_credits.get(),
                future_credits=self.tgt_future_credits.get(),
                target_cgpi=self.tgt_target_cgpi.get(),
            )
        except calc.ValidationError as e:
            messagebox.showerror("Validation error", str(e))
            return

        text = f"Required SGPI = {result['required_sgpi']}"
        if result["message"]:
            text += f"\n\n{result['message']}"
        self.tgt_result_label.config(text=text)

    # =======================================================================
    # HISTORY (list / edit / delete / export)
    # =======================================================================

    def _build_history_tab(self):
        frame = self.history_tab
        ttk.Label(frame, text="Semester History", font=("", 14, "bold")).pack(anchor="w", pady=(4, 8))

        self.history_table = ttk.Treeview(
            frame, columns=("id", "semester", "sgpi", "credits"), show="headings", height=14
        )
        for col, text, width in [
            ("id", "ID", 0), ("semester", "Semester", 100),
            ("sgpi", "SGPI", 100), ("credits", "Total Credits", 120),
        ]:
            self.history_table.heading(col, text=text)
            self.history_table.column(col, width=width, anchor="center")
        # Hide the raw id column visually but keep it for lookups
        self.history_table.column("id", width=0, stretch=False)
        self.history_table["displaycolumns"] = ("semester", "sgpi", "credits")
        self.history_table.pack(fill="both", expand=True, pady=4)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="Edit selected", command=self.edit_selected_semester).pack(side="left")
        ttk.Button(btns, text="Delete selected", command=self.delete_selected_semester).pack(side="left", padx=6)
        ttk.Button(btns, text="Export selected to CSV...", command=self.export_selected_semester).pack(side="left")

    def refresh_history(self):
        self.history_table.delete(*self.history_table.get_children())
        for s in db.get_all_semesters():
            self.history_table.insert(
                "", "end", iid=str(s["id"]),
                values=(s["id"], s["semester_number"], s["sgpi"], s["total_credits"]),
            )

    def _get_selected_semester_id(self):
        selection = self.history_table.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a semester in the table first.")
            return None
        return int(selection[0])

    def edit_selected_semester(self):
        semester_id = self._get_selected_semester_id()
        if semester_id is None:
            return
        semester = db.get_semester(semester_id)
        if semester is None:
            messagebox.showerror("Not found", "That semester no longer exists.")
            self.refresh_history()
            return
        self.load_semester_into_sgpi_form(semester)

    def delete_selected_semester(self):
        semester_id = self._get_selected_semester_id()
        if semester_id is None:
            return
        if not messagebox.askyesno("Confirm delete", "Delete this semester? This cannot be undone."):
            return
        db.delete_semester(semester_id)
        self.refresh_history()
        self.refresh_dashboard()
        messagebox.showinfo("Deleted", "Semester deleted.")

    def export_selected_semester(self):
        semester_id = self._get_selected_semester_id()
        if semester_id is None:
            return
        semester = db.get_semester(semester_id)
        if semester is None:
            messagebox.showerror("Not found", "That semester no longer exists.")
            self.refresh_history()
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"semester_{semester['semester_number']}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Subject", "Credits", "Grade"])
            for subj in semester["subjects"]:
                writer.writerow([subj["name"], subj["credits"], subj["grade"]])

        messagebox.showinfo("Exported", f"Saved to {path}")


if __name__ == "__main__":
    app = CGPIApp()
    app.mainloop()
