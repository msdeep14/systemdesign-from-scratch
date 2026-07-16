class PrimaryReplicaRouter:
    """
    A router to control all database operations on models in the
    application. Routes reads to 'replica' and writes to 'default' (primary).
    """

    def db_for_read(self, model, **hints):
        """
        Reads go to the replica.
        """
        return 'replica'

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
        db_set = {'default', 'replica'}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure migrations only run on the 'default' (primary) database.
        """
        if db == 'replica':
            return False
        return True
