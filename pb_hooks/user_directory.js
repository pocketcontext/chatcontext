// Commit an account change and its display label together, including inside batch transactions.
function sync(e, deleting) {
  const app = e.app;
  app.runInTransaction((txApp) => {
    e.app = txApp;
    try {
      e.next();
      const rows = txApp.findRecordsByFilter("user_directory", "id = {:id}", "", 1, 0, {id: e.record.id});
      if (deleting) {
        if (rows.length) txApp.delete(rows[0]);
        return;
      }
      const row = rows.length ? rows[0] : new Record(txApp.findCollectionByNameOrId("user_directory"));
      // Account names (including Google profile names) are private identity
      // data. Only an explicitly configured public alias may leave users.
      const name = e.record.getString("public_display_name").trim() || "User";
      if (rows.length && row.getString("name") === name) return;
      row.set("id", e.record.id);
      row.set("name", name);
      txApp.save(row);
    } finally {
      e.app = app;
    }
  });
}

module.exports = {sync};
