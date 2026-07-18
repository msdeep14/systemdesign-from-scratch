import random
from django.conf import settings

class PrimaryReplicaRouter:
    """
    A router to control all database operations on models in the
    application. Routes reads to 'replica_X' and writes to 'default' (primary).
    """
    def __init__(self):
        # Identify all replica database aliases
        self.replicas = [alias for alias in settings.DATABASES.keys() if alias.startswith('replica_')]
        if not self.replicas:
            # Fallback for old single replica name or no replicas
            if 'replica' in settings.DATABASES:
                self.replicas = ['replica']
            else:
                self.replicas = ['default']

    def db_for_read(self, model, **hints):
        """
        Reads go to a random replica.
        """
        return random.choice(self.replicas)

    def db_for_write(self, model, **hints):
        """
        Writes always go to primary (default).
        """
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Relations between objects are allowed if both objects are
        in the primary/replica pool.
        """
        db_set = {'default'} | set(self.replicas)
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure migrations only run on the 'default' (primary) database.
        """
        if db.startswith('replica'):
            return False
        return True
