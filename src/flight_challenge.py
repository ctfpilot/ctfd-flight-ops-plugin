from os import path

from CTFd.models import Challenges, Solves, db
from CTFd.plugins.dynamic_challenges import DynamicValueChallenge
from CTFd.plugins.dynamic_challenges.decay import DECAY_FUNCTIONS, logarithmic

from .routes import blueprint


PLUGIN_FOLDER_NAME = path.basename(path.dirname(__file__))


class FlightOpsChallenge(Challenges):
    __mapper_args__ = {"polymorphic_identity": "flightops"}
    id = db.Column(
        db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"),
        primary_key=True,
    )
    template_name = db.Column(db.String(255), index=False, default="")
    instance_type = db.Column(db.String(255), index=False, default="")

    initial = db.Column(db.Integer, default=0)
    minimum = db.Column(db.Integer, default=0)
    decay = db.Column(db.Integer, default=0)
    function = db.Column(db.String(32), default="logarithmic_custom")

    def __init__(self, *args, **kwargs):
        super().__init__(**kwargs)
        self.template_name = kwargs["template_name"]
        self.instance_type = kwargs.get("instance_type", "")
        self.value = kwargs["initial"]


class FlightOpsChallengeType(DynamicValueChallenge):
    id = "flightops"
    name = "flightops"
    templates = {
        "create": f"/plugins/{PLUGIN_FOLDER_NAME}/templates/create.html",
        "update": f"/plugins/{PLUGIN_FOLDER_NAME}/templates/update.html",
        "view": f"/plugins/{PLUGIN_FOLDER_NAME}/assets/view.html",
    }
    scripts = {
        "create": f"/plugins/{PLUGIN_FOLDER_NAME}/assets/create.js",
        "update": f"/plugins/{PLUGIN_FOLDER_NAME}/assets/update.js",
        "view": f"/plugins/{PLUGIN_FOLDER_NAME}/assets/view.js",
    }
    route = f"/plugins/{PLUGIN_FOLDER_NAME}/assets/"
    blueprint = blueprint
    challenge_model = FlightOpsChallenge

    @classmethod
    def read(cls, challenge):
        challenge = FlightOpsChallenge.query.filter_by(id=challenge.id).first()

        data = {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "initial": challenge.initial,
            "decay": challenge.decay,
            "minimum": challenge.minimum,
            "template_name": challenge.template_name,
            "instance_type": challenge.instance_type,
            "description": challenge.description,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            "type_data": {
                "id": cls.id,
                "name": cls.name,
                "templates": cls.templates,
                "scripts": cls.scripts,
            },
        }
        return data

    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()
        for attr, value in data.items():
            if attr in ("initial", "minimum", "decay"):
                value = float(value)
            setattr(challenge, attr, value)

        return FlightOpsChallengeType.calculate_value(challenge)

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)
        FlightOpsChallengeType.calculate_value(challenge)
