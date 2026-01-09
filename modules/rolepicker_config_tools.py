import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


ROLE_PICKER_STATE_FILE = Path(__file__).parent.parent / "picker_states.json"
ROLE_PICKER_STATE_FILE.touch(exist_ok=True)


@dataclass
class RolePickerRole:
    name: str
    id: int


@dataclass
class RolePickerState:
    title: str
    roles: list[RolePickerRole] = field(default_factory=list)
    message_ids: list[int] = field(default_factory=list)
    created_at: str | None = None


@dataclass
class RolePickerStates:
    states: list[RolePickerState] = field(default_factory=list)

    @staticmethod
    def load() -> "RolePickerStates":
        if not ROLE_PICKER_STATE_FILE.exists():
            return RolePickerStates()

        try:
            with open(ROLE_PICKER_STATE_FILE, 'r', encoding='utf-8') as f:
                data: list[dict[str, Any]] = json.load(f)

            states = []
            for state_data in data:
                roles = [
                    RolePickerRole(name=str(role['name']), id=int(role['id']))
                    for role in state_data.get('roles', [])
                ]

                state = RolePickerState(
                    title=state_data['title'],
                    roles=roles,
                    message_ids=state_data.get('message_ids', []),
                    created_at=state_data.get('created_at', 'unknown')
                )
                states.append(state)

            return RolePickerStates(states=states)
        except (json.JSONDecodeError, IOError, KeyError):
            return RolePickerStates()

    def save(self):
        data = []
        for state in self.states:
            data.append({
                'title': state.title,
                'roles': [{'name': role.name, 'id': role.id} for role in state.roles],
                'message_ids': state.message_ids,
                'created_at': state.created_at
            })

        with open(ROLE_PICKER_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


def reload_role_picker_states() -> RolePickerStates:
    return RolePickerStates.load()
