"""Command line.

  python -m app serve                      run the web app (one worker — see app/core/jobs.py)
  python -m app migrate                    bring every database to the latest schema
  python -m app set-password USER PASS     reset a password
  python -m app backup [DIR]               write a backup snapshot now (default: data/backups/<today>)
  python -m app <module> <command> ...     module commands, e.g. `pricing crawl`
"""
import sys


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    if cmd == "serve":
        import uvicorn
        from .core import config
        uvicorn.run("app.main:create_app", factory=True, host=config.HOST, port=config.PORT, workers=1,
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1")
        return

    from .core import config, modules
    from .main import init_storage
    modules.load(config.MODULES)
    init_storage()

    if cmd == "migrate":
        print("databases are up to date")
    elif cmd == "set-password" and len(args) == 3:
        from .core import auth, db
        auth.check_password_strength(args[2])
        with db.core.tx() as con:
            n = con.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                            (auth.hash_password(args[2]), args[1])).rowcount
            con.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = ?)", (args[1],))
        print("password changed" if n else "user not found")
        sys.exit(0 if n else 1)
    elif cmd == "backup":
        from pathlib import Path
        from .core import backup
        print(backup.snapshot(Path(args[1]) if len(args) > 1 else None))
    elif cmd in modules.loaded and len(args) > 1 and args[1] in modules.loaded[cmd].cli:
        modules.loaded[cmd].cli[args[1]](args[2:])
    else:
        print(__doc__)
        sys.exit(1)


main()
