// static/js/main.js

document.addEventListener("DOMContentLoaded", () => {
    // SGPA chart
    if (typeof sgpaData !== "undefined" && sgpaData && sgpaData.length) {
        const ctx = document.getElementById("sgpaChart");
        if (ctx) {
            const labels = sgpaData.map(r => r.semester);
            const sgpas = sgpaData.map(r => r.sgpa);

            new Chart(ctx, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [{
                        label: "SGPA",
                        data: sgpas,
                        fill: false,
                        borderColor: '#2563eb',
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: true }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            suggestedMax: 10
                        }
                    }
                }
            });
        }
    }

    // Grade distribution chart
    if (typeof gradeCounts !== "undefined" && gradeCounts) {
        const gc = gradeCounts;
        const labels = Object.keys(gc);
        const values = Object.values(gc);

        const gctx = document.getElementById("gradeChart");
        if (gctx) {
            new Chart(gctx, {
                type: "bar",
                data: {
                    labels: labels,
                    datasets: [{
                        label: "No. of Subjects",
                        data: values,
                        backgroundColor: '#60a5fa'
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            precision: 0
                        }
                    }
                }
            });
        }
    }
});