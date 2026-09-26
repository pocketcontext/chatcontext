migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  users.fields.add(new TextField({name: "public_display_name", max: 200}));
  app.save(users);

  // Replace persisted private names too, before the upgraded server accepts
  // requests. Do not infer consent to publish from an existing account name.
  // Page by immutable IDs so this covers directories larger than one batch.
  let after = "";
  while (true) {
    const rows = app.findRecordsByFilter("user_directory", "id > {:after}", "id", 500, 0, {after});
    if (!rows.length) break;
    for (const row of rows) {
      const accounts = app.findRecordsByFilter("users", "id = {:id}", "", 1, 0, {id: row.id});
      const name = accounts.length ? accounts[0].getString("public_display_name").trim() : "";
      row.set("name", name || "User");
      app.save(row);
    }
    after = rows[rows.length - 1].id;
  }
}, () => {
  throw new Error("Public display name rollback requires a deliberate backup restore.");
});
