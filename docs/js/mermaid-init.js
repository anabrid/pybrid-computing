document.addEventListener("DOMContentLoaded", function () {
    if (typeof mermaid === "undefined") {
        return;
    }
    mermaid.initialize({
        startOnLoad: false,
        theme: "default",
        securityLevel: "loose",
        flowchart: { useMaxWidth: true, htmlLabels: true },
    });

    document.querySelectorAll("pre.mermaid, .mermaid").forEach(function (el) {
        var source = el.textContent;
        var host = document.createElement("div");
        host.className = "mermaid";
        host.textContent = source;
        el.replaceWith(host);
    });

    mermaid.run({ querySelector: ".mermaid" });
});
