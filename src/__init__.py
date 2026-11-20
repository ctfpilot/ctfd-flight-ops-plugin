from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES

from .flight_challenge import FlightOpsChallengeType, PLUGIN_FOLDER_NAME
from .routes import register_app


CHALLENGE_CLASSES["flightops"] = FlightOpsChallengeType


def load(app):
    register_plugin_assets_directory(
        app,
        base_path=f"/plugins/{PLUGIN_FOLDER_NAME}/assets/",
    )

    app.db.create_all()
    register_app(app)
