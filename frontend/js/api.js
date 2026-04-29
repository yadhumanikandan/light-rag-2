// Lightweight API helpers shared across panels.
const Api = {
  async post(path, formData) {
    const resp = await fetch(path, { method: "POST", body: formData });
    if (!resp.ok) {
      let msg = `Request failed (${resp.status})`;
      try { const j = await resp.json(); if (j.error) msg = j.error; }
      catch (_) { /* ignore */ }
      throw new Error(msg);
    }
    return resp.json();
  },
};
