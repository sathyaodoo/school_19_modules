/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class SchoolDashboard extends Component {
    static template = "ad_school_management.SchoolDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            stats: {},
            loading: true
        });

        onWillStart(async () => {
            await this.loadStats();
        });
    }

    async loadStats() {
        this.state.loading = true;
        try {
            const result = await this.orm.call("school.dashboard", "get_dashboard_stats", []);
            this.state.stats = result;
        } catch (error) {
            console.error("Failed to load school dashboard statistics:", error);
        } finally {
            this.state.loading = false;
        }
    }

    openView(resModel, viewMode, domain = [], name = "") {
        const views = viewMode.split(',').map(mode => [false, mode.trim()]);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: resModel,
            views: views,
            view_mode: viewMode,
            domain: domain,
            target: "current"
        });
    }

    openStudents(status = null) {
        let domain = [];
        if (status) {
            domain = [["student_status", "=", status]];
        }
        this.openView("school.student", "list,form", domain, "Students");
    }

    openTeachers() {
        this.openView("school.teacher", "list,form", [], "Teachers");
    }

    openParents() {
        this.openView("school.parent", "list,form", [], "Parents");
    }

    openAdmissions(state = null) {
        let domain = [];
        if (state) {
            domain = [["state", "=", state]];
        }
        this.openView("school.admission", "list,form", domain, "Admissions");
    }

    openFees(state = null) {
        let domain = [];
        if (state) {
            domain = [["state", "=", state]];
        }
        this.openView("school.student.fee", "list,form", domain, "Student Fees");
    }

    openLibrary(state = null) {
        let domain = [];
        if (state) {
            domain = [["state", "=", state]];
        }
        this.openView("school.book.issue", "list,form", domain, "Book Issues");
    }

    openTransport() {
        this.openView("school.transport.route", "list,form", [], "Transport Routes");
    }

    openHostel() {
        this.openView("school.hostel.allocation", "list,form", [], "Hostel Allocations");
    }
}

registry.category("actions").add("school_dashboard", SchoolDashboard);
