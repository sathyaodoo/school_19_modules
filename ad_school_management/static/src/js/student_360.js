/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Student 360° Digital Profile (BRS Part III-3): academic, development,
 * reading & creativity and social responsibility in one holistic view.
 */
export class Student360 extends Component {
    static template = "ad_school_management.Student360";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const params = (this.props.action && this.props.action.params) || {};
        this.state = useState({ studentId: params.student_id || false, yearId: false, data: {}, loading: false,
                                term: "", results: [] });
        onWillStart(async () => {
            if (this.state.studentId) {
                await this.load();
            } else {
                await this.search();
            }
        });
    }

    async load() {
        if (!this.state.studentId) return;
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("school.student", "get_student_360",
                [this.state.studentId], { year_id: this.state.yearId });
        } finally {
            this.state.loading = false;
        }
    }

    async search() {
        this.state.results = await this.orm.call("school.student", "search_360_students", [this.state.term]);
    }

    async onSearchInput(ev) {
        this.state.term = ev.target.value;
        await this.search();
    }

    async pick(studentId) {
        this.state.studentId = studentId;
        this.state.results = [];
        await this.load();
    }

    async changeStudent() {
        this.state.studentId = false;
        this.state.data = {};
        this.state.term = "";
        await this.search();
    }

    async onYearChange(ev) {
        this.state.yearId = parseInt(ev.target.value) || false;
        await this.load();
    }

    openStudent() {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "school.student",
            res_id: this.state.studentId, views: [[false, "form"]], target: "current" });
    }

    openList(model, name, extraDomain = []) {
        // Development records can cover many students (Many2many "student_ids");
        // competency assessments and club memberships still use one "student_id".
        const manyStudents = model === "school.student.record";
        const studentId = this.state.studentId;
        this.action.doAction({
            type: "ir.actions.act_window", name, res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: manyStudents
                ? [["student_ids", "in", [studentId]], ...extraDomain]
                : [["student_id", "=", studentId], ...extraDomain],
            context: manyStudents
                ? { default_student_ids: [[4, studentId]] }
                : { default_student_id: studentId },
            target: "current",
        });
    }

    print() {
        this.action.doAction("ad_school_management.action_report_student_360", {
            additionalContext: { active_ids: [this.state.studentId], active_model: "school.student" },
        });
    }

    levelClass(level) {
        return { 1: "text-bg-danger", 2: "text-bg-warning", 3: "text-bg-info", 4: "text-bg-success" }[level] || "text-bg-light";
    }

    trendIcon(trend) {
        return { up: "fa-arrow-up text-success", down: "fa-arrow-down text-danger", steady: "fa-arrow-right text-muted" }[trend] || "";
    }
}

registry.category("actions").add("school_student_360", Student360);