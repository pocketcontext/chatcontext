#!/usr/bin/env python3
"""Upgrade a synthetic legacy directory without retaining private account names."""
import argparse
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = '1790300300_public_display_names.js'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='chatcontext-directory-upgrade-') as tmp:
        root = Path(tmp)
        migrations = root / 'pb_migrations'
        migrations.mkdir()
        hooks = root / 'pb_hooks'
        hooks.mkdir()
        for source in sorted((ROOT / 'pb_migrations').glob('*.js')):
            if source.name < MIGRATION:
                shutil.copy2(source, migrations / source.name)
        # Use PocketBase records, with isolated synthetic data only. More than
        # one migration batch includes stale directory entries without accounts.
        (migrations / '1790300250_synthetic_directory.js').write_text('''
migrate((app) => {
  const users = app.findCollectionByNameOrId("users");
  const directory = app.findCollectionByNameOrId("user_directory");
  const user = new Record(users);
  user.set("id", "syntheticuser01");
  user.set("email", "private@example.test");
  user.set("name", "Private Legal Name");
  user.setPassword("SyntheticPassword123!");
  app.save(user);
  for (let i = 0; i < 502; i++) {
    const row = new Record(directory);
    row.set("id", i === 0 ? user.id : "orphan" + String(i).padStart(9, "0"));
    row.set("name", "Legacy private name " + i);
    app.save(row);
  }
}, () => {});
''')
        common = [str(Path(args.binary).resolve()), '--dir', str(root / 'pb_data'),
                  '--migrationsDir', str(migrations), '--hooksDir', str(hooks)]
        def migrate():
            result = subprocess.run(common + ['migrate', 'up'], cwd=ROOT, capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
        def rows(sql):
            with sqlite3.connect(f'file:{root / "pb_data" / "data.db"}?mode=ro', uri=True) as db:
                return db.execute(sql).fetchall()
        migrate()
        assert rows('SELECT count(*) FROM user_directory WHERE name LIKE "Legacy private name %"') == [(502,)]
        assert 'public_display_name' not in {row[1] for row in rows('PRAGMA table_info(users)')}
        shutil.copy2(ROOT / 'pb_migrations' / MIGRATION, migrations / MIGRATION)
        migrate()
        assert rows('SELECT DISTINCT name FROM user_directory') == [('User',)]
        assert rows('SELECT count(*) FROM user_directory') == [(502,)]
        assert rows('SELECT name, public_display_name FROM users') == [('Private Legal Name', '')]
        migrate()
        assert rows('SELECT DISTINCT name FROM user_directory') == [('User',)]
    print('PASS: legacy private names scrubbed across migration batches and orphan directory rows')


if __name__ == '__main__':
    main()
