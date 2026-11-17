"""Per-profile publishing credentials. Legacy settings belong to Default."""
import threading
from publisher import Publisher


class ProfileSettings:
    def __init__(self, store, profile_id):
        self.store, self.profile_id = store, profile_id

    def _key(self, key):
        return key if self.profile_id == 'default' else f'profile:{self.profile_id}:{key}'

    def get_setting(self, key):
        return self.store.get_setting(self._key(key))

    def set_setting(self, key, value):
        return self.store.set_setting(self._key(key), value)

    def delete_setting(self, key):
        return self.store.delete_setting(self._key(key))

    def __getattr__(self, name):
        return getattr(self.store, name)


class ProfileAccounts:
    def __init__(self, store, client_path, default):
        self.store, self.client_path = store, client_path
        self.publishers = {'default': default}
        self.lock = threading.Lock()

    def publisher(self, profile_id):
        if not self.store.get_profile(profile_id):
            raise ValueError('Profile not found.')
        with self.lock:
            if profile_id not in self.publishers:
                self.publishers[profile_id] = Publisher(ProfileSettings(self.store, profile_id), self.client_path)
            return self.publishers[profile_id]

    def callback(self, port, query):
        state = (query.get('state') or [''])[0]
        with self.lock:
            publishers = list(self.publishers.values())
        for publisher in publishers:
            with publisher.lock:
                found = state in publisher.pending
            if found:
                return publisher.finish_connect(port, query)
        # Keep the normal expired-state error without ever choosing an account by active UI state.
        return self.publishers['default'].finish_connect(port, query)
