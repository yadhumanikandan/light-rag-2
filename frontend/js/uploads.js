// Reusable drag-drop / browse slot. Files for a slot are kept in slot._files.
const Uploads = (() => {
  function attach(slot, { multi = false } = {}) {
    slot._files = [];
    const input = slot.querySelector("input[type=file]");
    const action = slot.querySelector(".slot-action");
    const list = slot.querySelector(".file-list");

    const setFiles = (files) => {
      slot._files = files;
      slot.classList.toggle("has-files", files.length > 0);
      render();
      slot.dispatchEvent(new CustomEvent("upload:change", { detail: { files } }));
    };

    const render = () => {
      list.innerHTML = "";
      slot._files.forEach((f, idx) => {
        const pill = document.createElement("div");
        pill.className = "file-pill";
        pill.innerHTML = `<span title="${f.name}">${f.name}</span><button type="button" aria-label="Remove">✕</button>`;
        pill.querySelector("button").addEventListener("click", (e) => {
          e.stopPropagation();
          const next = slot._files.slice();
          next.splice(idx, 1);
          setFiles(next);
        });
        list.appendChild(pill);
      });
    };

    const ingest = (fileList) => {
      const incoming = Array.from(fileList || []);
      if (!incoming.length) return;
      setFiles(multi ? slot._files.concat(incoming) : [incoming[0]]);
    };

    action.addEventListener("click", (e) => { e.preventDefault(); input.click(); });
    slot.addEventListener("click", (e) => {
      if (e.target.closest(".file-pill") || e.target.closest(".slot-action")) return;
      input.click();
    });

    input.addEventListener("change", () => { ingest(input.files); input.value = ""; });

    ["dragenter", "dragover"].forEach(ev =>
      slot.addEventListener(ev, (e) => { e.preventDefault(); slot.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach(ev =>
      slot.addEventListener(ev, (e) => { e.preventDefault(); slot.classList.remove("dragover"); })
    );
    slot.addEventListener("drop", (e) => { ingest(e.dataTransfer.files); });

    slot._reset = () => setFiles([]);
    return slot;
  }

  return { attach };
})();
