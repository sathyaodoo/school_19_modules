/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class CompetitionNotebook extends Component {
    static template = "ad_school_management.CompetitionNotebook";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            activeId: false,
            students: [],
            classes: [],
        });

        onWillStart(async () => {
            const [students, classes] = await Promise.all([
                this.orm.searchRead(
                    "school.student",
                    [["student_status", "!=", "alumni"]],
                    ["name", "class_id"],
                    { limit: 1000, order: "id asc" }
                ),
                this.orm.searchRead(
                    "school.class",
                    [],
                    ["name"],
                    { limit: 1000, order: "name asc" }
                ),
            ]);

            this.state.students = students.map((student) => ({
                id: student.id,
                name: student.name,
                classId: student.class_id ? student.class_id[0] : false,
            }));

            this.state.classes = classes.map((schoolClass) => ({
                id: schoolClass.id,
                name: schoolClass.name,
            }));
        });
    }

    get list() {
        return this.props.record.data[this.props.name];
    }

    get competitions() {
        const records =
            this.props.record.data.competition_ids?.records || [];

        return records.map((record) => ({
            id: record.resId || record.data.id,
            name:
                record.data.display_name ||
                record.data.name ||
                "Competition",
        }));
    }

    get activeCompetition() {
        return (
            this.competitions.find(
                (competition) => competition.id === this.state.activeId
            ) ||
            this.competitions[0] ||
            false
        );
    }

    get rows() {
        const competition = this.activeCompetition;

        if (!competition || !this.list) {
            return [];
        }

        return this.list.records.filter(
            (row) =>
                row.data.competition_id &&
                row.data.competition_id.id === competition.id
        );
    }

    get classOptions() {
        return this.state.classes;
    }

    studentsForRow(row) {
        const classId = this.classId(row);

        if (!classId) {
            return [];
        }

        return this.state.students.filter(
            (student) => student.classId === classId
        );
    }

    selectTab(comp) {
        this.state.activeId = comp.id;
    }

    textValue(row, name) {
        return row.data[name] || "";
    }

    classId(row) {
        return row.data.class_id
            ? row.data.class_id.id
            : false;
    }

    classText(row) {
        return row.data.class_id
            ? row.data.class_id.display_name
            : "";
    }

    studentId(row) {
        return row.data.student_id
            ? row.data.student_id.id
            : false;
    }

    studentText(row) {
        return row.data.student_id
            ? row.data.student_id.display_name
            : "";
    }

    async updateClass(row, ev) {
        const classId = parseInt(ev.target.value, 10) || false;

        const selectedClass = this.classOptions.find(
            (schoolClass) => schoolClass.id === classId
        );

        await row.update({
            class_id: selectedClass
                ? {
                    id: selectedClass.id,
                    display_name: selectedClass.name,
                }
                : false,
            student_id: false,
        });
    }

    async updateStudent(row, ev) {
        const studentId = parseInt(ev.target.value, 10) || false;

        const selectedStudent = this.studentsForRow(row).find(
            (student) => student.id === studentId
        );

        await row.update({
            student_id: selectedStudent
                ? {
                    id: selectedStudent.id,
                    display_name: selectedStudent.name,
                }
                : false,
        });
    }

    async updateText(row, name, ev) {
        await row.update({
            [name]: ev.target.value,
        });
    }

    certificateUrl(row) {
        if (!row.resId || !row.data.certificate_filename) {
            return false;
        }

        return (
            `/web/content/school.student.competition.participant/${row.resId}` +
            `/certificate/${encodeURIComponent(
                row.data.certificate_filename
            )}?download=true`
        );
    }

    async onCertificateSelected(row, ev) {
        const file = ev.target.files[0];

        if (!file) {
            return;
        }

        const data = await new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = () => {
                resolve(reader.result.split(",")[1]);
            };

            reader.onerror = reject;
            reader.readAsDataURL(file);
        });

        await row.update({
            certificate: data,
            certificate_filename: file.name,
        });

        ev.target.value = "";
    }

    async clearCertificate(row) {
        await row.update({
            certificate: false,
            certificate_filename: false,
        });
    }

    async addRow() {
        const competition = this.activeCompetition;

        if (!competition || !this.list) {
            return;
        }

        const row = await this.list.addNewRecord({
            context: {
                default_competition_id: competition.id,
            },
            mode: "edit",
            position: "bottom",
        });

        if (row) {
            await row.update({
                competition_id: {
                    id: competition.id,
                    display_name: competition.name,
                },
            });
        }
    }

    async removeRow(row) {
        if (this.list) {
            await this.list.delete(row);
        }
    }
}

registry.category("fields").add("competition_notebook", {
    component: CompetitionNotebook,
    supportedTypes: ["one2many"],

    relatedFields: () => [
        {
            name: "competition_id",
            type: "many2one",
            relation: "school.competition",
        },
        {
            name: "class_id",
            type: "many2one",
            relation: "school.class",
        },
        {
            name: "student_id",
            type: "many2one",
            relation: "school.student",
        },
        {
            name: "result",
            type: "char",
        },
        {
            name: "certificate",
            type: "binary",
        },
        {
            name: "certificate_filename",
            type: "char",
        },
    ],
});