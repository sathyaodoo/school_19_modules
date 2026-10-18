/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

function emptyStats() {
    return {
        has_library: false,
        has_hostel: false,
        students: { total: 0, enrolled: 0, draft: 0, promoted: 0 },
        faculty_parents: { teachers: 0, parents: 0 },
        admissions: { total: 0, pending: 0, approved: 0 },
        library: { books: 0, borrowed: 0 },
        transport: { vehicles: 0, routes: 0 },
        hostel: { total_beds: 0, occupied_beds: 0, available_beds: 0, occupancy_rate: 0 },
        finance: { paid: 0, outstanding: 0, total: 0, collection_rate: 0 },
        attendance: { marked: 0, present: 0, rate: 0 },
    };
}

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

        // (Staff Leave Requests moved to Teacher Development > Growth Dashboard)
        // Live House Championship: reload the standings every 30 seconds.
        this.championshipTimer = setInterval(() => this.loadChampionship(), 30000);
        onWillUnmount(() => {
            clearInterval(this.championshipTimer);
        });
    }

    async loadChampionship() {
        try {
            this.state.stats.championship = await this.orm.call("school.house.point", "get_championship", []);
        } catch (error) {
            console.error("Failed to refresh the house championship:", error);
        }
    }

    openHousePoints(houseId = null) {
        // Only the boards currently shown on the dashboard (follows the company switcher).
        const boards = ((this.state.stats.championship || {}).boards || []).map((b) => b.board);
        let domain = [["state", "=", "confirmed"]];
        if (houseId) {
            domain.push(["house_id", "=", houseId]);
        } else if (boards.length) {
            domain.push(["board", "in", boards]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "House Points",
            res_model: "school.house.point",
            views: [[false, "list"], [false, "form"], [false, "pivot"], [false, "graph"]],
            domain: domain,
            context: houseId ? { default_house_id: houseId } : {},
            target: "current",
        });
    }


    openEarlyWarnings(filter = null) {
        // Early warning alerts (only staff who may see them get this panel).
        const domains = {
            to_review: [["state", "=", "to_review"]],
            to_review_red: [["state", "=", "to_review"], ["suggested_level", "=", "red"]],
            red: [["state", "=", "in_progress"], ["confirmed_level", "=", "red"]],
            amber: [["state", "=", "in_progress"], ["confirmed_level", "=", "amber"]],
            follow_up_due: [["state", "=", "in_progress"], ["follow_up_date", "<=", luxon.DateTime.now().toISODate()]],
        };
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Early Warnings",
            res_model: "school.early.warning",
            views: [[false, "list"], [false, "form"]],
            domain: domains[filter] || [["state", "in", ["to_review", "in_progress"]]],
            target: "current",
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
