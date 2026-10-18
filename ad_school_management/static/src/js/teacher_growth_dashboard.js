/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Teacher Growth Dashboard (BRS Part XV-19).
 * Teachers: their own portfolio. Principal / HR / Admin: school overview,
 * and any teacher's portfolio (click a teacher).
 */
export class TeacherGrowthDashboard extends Component {
    static template = "ad_school_management.TeacherGrowthDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const params = (this.props.action && this.props.action.params) || {};
        this.state = useState({ data: {}, loading: true, teacherId: params.teacher_id || false, yearId: false });
        onWillStart(() => this.load());

        // Staff Leave Requests: live update. When an employee applies for
        // leave, the server sends 'school_leave_request' to Admin / HR (see
        // hr.leave _school_push_dashboard_alert); only the leave panel reloads.
        this.busService = useService("bus_service");
        this.onLeaveRequest = () => this.loadLeaveStats();
        this.busService.subscribe("school_leave_request", this.onLeaveRequest);
        onWillUnmount(() => this.busService.unsubscribe("school_leave_request", this.onLeaveRequest));
    }

    async loadLeaveStats() {
        try {
            this.state.data.leaves = await this.orm.call("school.dashboard", "get_leave_stats", []);
        } catch (error) {
            console.error("Failed to refresh leave requests:", error);
        }
    }

    openLeaveApprovals(stage = null) {
        const domain = [["holiday_status_id.school_approval_workflow", "=", true]];
        if (stage) {
            domain.push(["school_approval_stage", "=", stage]);
        } else {
            domain.push(["school_approval_stage", "in", ["admin", "hr", "principal"]]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Leave Requests",
            res_model: "hr.leave",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openLeave(leaveId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Leave Request",
            res_model: "hr.leave",
            res_id: leaveId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("school.pd.activity", "get_growth_dashboard", [],
                { teacher_id: this.state.teacherId, year_id: this.state.yearId });
        } finally {
            this.state.loading = false;
        }
    }

    async openTeacher(teacherId) {
        this.state.teacherId = teacherId;
        await this.load();
    }

    async backToOverview() {
        this.state.teacherId = false;
        await this.load();
    }

    async onYearChange(ev) {
        this.state.yearId = parseInt(ev.target.value) || false;
        await this.load();
    }

    // own = true: the "My portfolio" block shown under the school overview. Its clicks must be limited
    // to the logged-in teacher's own records, while the school-wide overview cards stay unfiltered.
    _teacherDomain(own = false) {
        const portfolio = own ? this.state.data.my_portfolio : this.state.data.portfolio;
        return portfolio ? [["teacher_id", "=", portfolio.teacher.id]] : [];
    }

    _yearDomain() {
        const year = this.state.data.year;
        return year ? [["academic_year_id", "=", year.id]] : [];
    }

    openList(model, name, extraDomain = [], own = false) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: [...this._teacherDomain(own), ...extraDomain],
            target: "current",
        });
    }

    openActivities(typeId = null, state = null, own = false) {
        const domain = [...this._yearDomain()];
        if (typeId) domain.push(["type_id", "=", typeId]);
        if (state) domain.push(["state", "=", state]);
        this.openList("school.pd.activity", "PD Activities", domain, own);
    }

    openActivity(id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "school.pd.activity", res_id: id,
            views: [[false, "form"]], target: "current" });
    }

    newActivity(typeId = null) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "school.pd.activity",
            views: [[false, "form"]], target: "current",
            context: typeId ? { default_type_id: typeId } : {} });
    }

    openGoals(own = false) {
        this.openList("school.teacher.pd.goal", "Annual PD Goals", this._yearDomain(), own);
    }

    openReflections(own = false) {
        this.openList("school.teacher.reflection", "Self-Reflections", this._yearDomain(), own);
    }

    printPortfolio() {
        const portfolio = this.state.data.portfolio;
        if (!portfolio) return;
        this.action.doAction("ad_school_management.action_report_teacher_growth_portfolio", {
            additionalContext: { active_ids: [portfolio.teacher.id], active_model: "school.teacher" },
        });
    }
}

registry.category("actions").add("school_teacher_growth_dashboard", TeacherGrowthDashboard);