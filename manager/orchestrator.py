"""Install and update all selected repositories from published GitHub releases.

Depends on private configuration, repository Dockerfiles, backend draining, and
database backups. Installed versions are published only after health checks pass.
"""
import hashlib
import json
from pathlib import Path

from manager.backend import drain, request_backend
from manager.backups import create_backup, restore_backup
from manager.catalog import enabled_components
from manager.commands import CommandRunner
from manager.configuration import SiteConfig
from manager.compose import render_compose
from manager.releases import GitHub, version_tuple
from manager.system import compose_command, preflight, require_free_ports
from manager.self_update import prepare_manager
from manager.demo import prepare_demo_photos


class Orchestrator:
    def __init__(self, store, configuration):
        self.store = store
        self.configuration = configuration

    def runner(self, log=None):
        config = self.configuration.load()
        credentials = self.configuration.credentials()
        return CommandRunner([config.github_token, config.nvr_password, *credentials.values()], log)

    def check_updates(self):
        config = self.configuration.load()
        github = GitHub(self.runner(), config.github_token)
        installed = self.store.read("installed", {})
        results = []
        for component in enabled_components(config):
            current = installed.get(component.key)
            try:
                latest = github.latest(component.repository)
                newer = not current or version_tuple(latest["tag"]) > version_tuple(current["tag"])
                if current and latest["tag"] == current["tag"] and latest["sha"] != current["sha"]:
                    raise ValueError("A published version changed its revision. Publish a new release instead.")
                results.append({"key": component.key, "name": component.name, "repository": component.repository,
                                "installed": current, "latest": latest, "update_available": newer, "error": None})
            except (ValueError, RuntimeError, OSError) as error:
                results.append({"key": component.key, "name": component.name, "repository": component.repository,
                                "installed": current, "latest": None, "update_available": False,
                                "error": self.runner().redact(str(error))})
        result = {"components": results, "updates_available": any(item["update_available"] for item in results)}
        self.store.write("updates", result)
        return result

    def install(self, log):
        self.apply(log, updating=False)

    def update_all(self, log):
        if not self.store.read("installed", {}):
            raise ValueError("Install the ecosystem before updating it.")
        self.apply(log, updating=True)

    def apply(self, log, updating):
        config = self.configuration.load()
        runner = self.runner(log)
        checks = preflight(runner, config.github_token)
        if not checks["ready"]:
            raise ValueError("Prerequisites failed: " + "; ".join(item["name"] for item in checks["checks"] if not item["ok"]))
        previous = self.store.read("installed", {})
        if previous and not updating:
            raise ValueError("The ecosystem is already installed. Use Update All or Start services.")
        if not updating:
            require_free_ports(config)
        log("Resolving published stable releases for every enabled repository.")
        updates = self.check_updates()
        failures = [item["name"] + ": " + item["error"] for item in updates["components"] if item["error"]]
        if failures:
            raise ValueError("\n".join(failures))
        targets = {}
        for item in updates["components"]:
            targets[item["key"]] = item["latest"] if item["update_available"] else item["installed"]
        installed_configuration = self.store.read("installed-configuration", None)
        if updating and targets == previous and installed_configuration == config.model_dump():
            log("Every component is already at its latest published stable release.")
            return
        github = GitHub(runner, config.github_token)
        for component in enabled_components(config):
            revision = targets[component.key]
            destination = self.store.root / "sources" / component.key / revision["sha"]
            if not destination.exists():
                log(f"Downloading {component.name} {revision['tag']}.")
                github.download(component.repository, revision["sha"], destination)
            if component.key != "manager" and not (destination / "Dockerfile").is_file():
                raise ValueError(f"{component.name} release {revision['tag']} has no Dockerfile.")
        credentials = self.configuration.credentials()
        compose = render_compose(self.store.root, config, credentials, targets)
        old_compose = self.store.read("compose", None)
        self.store.write("candidate-compose", compose)
        candidate_command = ["docker", "compose", "--project-name", "cabek-ai-manager", "--file", str(self.store.root / "candidate-compose.json")]
        log("Building selected service releases; existing services remain available.")
        runner.run([*candidate_command, "config", "--quiet"], timeout=30)
        runner.run([*candidate_command, "build"], timeout=3600)
        manager_update = prepare_manager(self.store, targets["manager"], runner, log)
        backup = None
        drained = False
        previous_config = SiteConfig.model_construct(**(installed_configuration or config.model_dump()))
        try:
            if updating:
                drained = True
                drain(previous_config, credentials, log)
                backup = create_backup(self.store, runner, log)
                runner.run(compose_command(self.store, "stop", "backend", "frontend"), timeout=90)
            self.store.write("compose", compose)
            self.seed_demo_photo()
            runner.run(compose_command(self.store, "up", "-d", "--wait", "--wait-timeout", "180", "database"), timeout=240)
            log("Applying database migrations and canonical reference seeders.")
            runner.run(compose_command(self.store, "run", "--rm", "--no-deps", "pricing", "php", "artisan", "migrate", "--force"), timeout=180)
            runner.run(compose_command(self.store, "run", "--rm", "--no-deps", "pricing", "php", "artisan", "db:seed", "--force"), timeout=180)
            runner.run(compose_command(self.store, "run", "--rm", "--no-deps", "-T", "pricing", "php", "artisan", "manager:configure"),
                       input_text=json.dumps({"name": "Cabek AI Manager", "token": credentials["autoestimate_token"]}), quiet=True)
            self.import_datasets(config, targets, runner, log)
            log("Starting the ecosystem and waiting for service health checks.")
            runner.run(compose_command(self.store, "up", "-d", "--wait", "--wait-timeout", "240", "--remove-orphans"), timeout=360)
            request_backend(config, credentials, "status")
            self.store.write("installed", targets)
            self.store.write("installed-configuration", config.model_dump())
            self.store.write("updates", {"components": [{**item, "installed": targets[item["key"]], "update_available": False}
                                                       for item in updates["components"]], "updates_available": False})
            if manager_update:
                self.store.write("manager-next", manager_update)
                log("Manager update prepared. The interface will reconnect after its restart.")
            log("All services are running at the selected published versions.")
        except Exception:
            if backup:
                log("Update failed; restoring the previous application and database.")
                try:
                    runner.run(compose_command(self.store, "stop", "backend", "frontend", "pricing", "pricing-web"), timeout=90)
                    restore_backup(self.store, runner, backup, log)
                except Exception as recovery:
                    raise RuntimeError("Update failed and automatic recovery failed: " + runner.redact(str(recovery))) from None
            elif updating and old_compose:
                self.store.write("compose", old_compose)
            elif not updating:
                # A retry must be able to reclaim its ports without deleting persistent SQL data.
                runner.run(compose_command(self.store, "stop"), timeout=120)
            raise
        finally:
            if drained:
                try:
                    active_config = config if self.store.read("installed", {}) == targets else previous_config
                    request_backend(active_config, credentials, "maintenance", {"enabled": False})
                except OSError:
                    log("Backend unavailable; maintenance will clear when the recovered backend starts.")

    def import_datasets(self, config, revisions, runner, log):
        source = self.store.root / "sources" / "autoestimate" / revisions["autoestimate"]["sha"] / "data"
        paths = [(p, "/imports/bundled/" + p.name) for p in source.glob("*.zip")]
        paths += [(Path(path), f"/imports/custom-{index}") for index, path in enumerate(config.dataset_paths)]
        imported = self.store.read("imports", {})
        for path, container_path in paths:
            files = [path] if path.is_file() else sorted(path.rglob("*.json"))
            digest = hashlib.sha256()
            for item in files:
                digest.update(item.name.encode())
                with item.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
            key = digest.hexdigest()
            if key in imported:
                continue
            log("Validating and importing pricing dataset: " + path.name)
            base = compose_command(self.store, "run", "--rm", "--no-deps", "pricing", "php", "artisan", "observations:import", container_path)
            runner.run([*base, "--dry-run"], timeout=600)
            runner.run([*base, "--yes"], timeout=900)
            imported[key] = path.name
            self.store.write("imports", imported)

    def seed_demo_photo(self):
        prepare_demo_photos(self.store.root / "data/mock-photos")
