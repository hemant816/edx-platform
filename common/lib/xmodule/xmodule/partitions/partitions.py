"""Defines ``Group`` and ``UserPartition`` models for partitioning"""

from collections import namedtuple

from stevedore.extension import ExtensionManager

# We use ``id`` in this file as the IDs of our Groups and UserPartitions,
# which Pylint disapproves of.
# pylint: disable=redefined-builtin


# UserPartition IDs must be unique. The Cohort and Random UserPartitions (when they are
# created via Studio) choose an unused ID in the range of 100 (historical) to MAX_INT. Therefore the
# dynamic UserPartitionIDs must be under 100, and they have to be hard-coded to ensure
# they are always the same whenever the dynamic partition is added (since the UserPartition
# ID is stored in the xblock group_access dict).
ENROLLMENT_TRACK_PARTITION_ID = 50

MINIMUM_STATIC_PARTITION_ID = 100


class UserPartitionError(Exception):
    """
    Base Exception for when an error was found regarding user partitions.
    """
    pass


class NoSuchUserPartitionError(UserPartitionError):
    """
    Exception to be raised when looking up a UserPartition by its ID fails.
    """
    pass


class NoSuchUserPartitionGroupError(UserPartitionError):
    """
    Exception to be raised when looking up a UserPartition Group by its ID fails.
    """
    pass

class ReadOnlyUserPartitionError(UserPartitionError):
    """
    Exception to be raised when attempting to modify a read only partition.
    """
    pass


class Group(namedtuple("Group", "id name")):
    """
    An id and name for a group of students.  The id should be unique
    within the UserPartition this group appears in.
    """
    # in case we want to add to this class, a version will be handy
    # for deserializing old versions.  (This will be serialized in courses)
    VERSION = 1

    def __new__(cls, id, name):
        return super(Group, cls).__new__(cls, int(id), name)

    def to_json(self):
        """
        'Serialize' to a json-serializable representation.

        Returns:
            a dictionary with keys for the properties of the group.
        """
        return {
            "id": self.id,
            "name": self.name,
            "version": Group.VERSION
        }

    @staticmethod
    def from_json(value):
        """
        Deserialize a Group from a json-like representation.

        Args:
            value: a dictionary with keys for the properties of the group.

        Raises TypeError if the value doesn't have the right keys.
        """
        if isinstance(value, Group):
            return value

        for key in ("id", "name", "version"):
            if key not in value:
                raise TypeError("Group dict {0} missing value key '{1}'".format(
                    value, key))

        if value["version"] != Group.VERSION:
            raise TypeError("Group dict {0} has unexpected version".format(
                value))

        return Group(value["id"], value["name"])


# The Stevedore extension point namespace for user partition scheme plugins.
USER_PARTITION_SCHEME_NAMESPACE = 'openedx.user_partition_scheme'


class UserPartition(namedtuple("UserPartition", "id name description groups scheme parameters active")):
    """A named way to partition users into groups, primarily intended for
    running experiments. It is expected that each user will be in at most one
    group in a partition.

    A Partition has an id, name, scheme, description, parameters, and a list
    of groups. The id is intended to be unique within the context where these
    are used. (e.g., for partitions of users within a course, the ids should
    be unique per-course). The scheme is used to assign users into groups.
    The parameters field is used to save extra parameters e.g., location of
    the block in case of VerificationPartitionScheme.

    Partitions can be marked as inactive by setting the "active" flag to False.
    Any group access rule referencing inactive partitions will be ignored
    when performing access checks.
    """
    VERSION = 3

    # The collection of user partition scheme extensions.
    scheme_extensions = None

    # The default scheme to be used when upgrading version 1 partitions.
    VERSION_1_SCHEME = "random"

    def __new__(cls, id, name, description, groups, scheme=None, parameters=None, active=True, scheme_id=VERSION_1_SCHEME):  # pylint: disable=line-too-long
        if not scheme:
            scheme = UserPartition.get_scheme(scheme_id)
        if parameters is None:
            parameters = {}

        return super(UserPartition, cls).__new__(cls, int(id), name, description, groups, scheme, parameters, active)

    @staticmethod
    def get_scheme(name):
        """
        Returns the user partition scheme with the given name.
        """
        # Note: we're creating the extension manager lazily to ensure that the Python path
        # has been correctly set up. Trying to create this statically will fail, unfortunately.
        if not UserPartition.scheme_extensions:
            UserPartition.scheme_extensions = ExtensionManager(namespace=USER_PARTITION_SCHEME_NAMESPACE)
        try:
            scheme = UserPartition.scheme_extensions[name].plugin
        except KeyError:
            raise UserPartitionError("Unrecognized scheme '{0}'".format(name))
        scheme.name = name
        return scheme

    def to_json(self):
        """
        'Serialize' to a json-serializable representation.

        Returns:
            a dictionary with keys for the properties of the partition.
        """
        return {
            "id": self.id,
            "name": self.name,
            "scheme": self.scheme.name,
            "description": self.description,
            "parameters": self.parameters,
            "groups": [g.to_json() for g in self.groups],
            "active": bool(self.active),
            "version": UserPartition.VERSION
        }

    @staticmethod
    def from_json(value):
        """
        Deserialize a Group from a json-like representation.

        Args:
            value: a dictionary with keys for the properties of the group.

        Raises TypeError if the value doesn't have the right keys.
        """
        if isinstance(value, UserPartition):
            return value

        for key in ("id", "name", "description", "version", "groups"):
            if key not in value:
                raise TypeError("UserPartition dict {0} missing value key '{1}'".format(value, key))

        if value["version"] == 1:
            # If no scheme was provided, set it to the default ('random')
            scheme_id = UserPartition.VERSION_1_SCHEME

        # Version changes should be backwards compatible in case the code
        # gets rolled back.  If we see a version number greater than the current
        # version, we should try to read it rather than raising an exception.
        elif value["version"] >= 2:
            if "scheme" not in value:
                raise TypeError("UserPartition dict {0} missing value key 'scheme'".format(value))

            scheme_id = value["scheme"]
        else:
            raise TypeError("UserPartition dict {0} has unexpected version".format(value))

        parameters = value.get("parameters", {})
        active = value.get("active", True)
        groups = [Group.from_json(g) for g in value["groups"]]
        scheme = UserPartition.get_scheme(scheme_id)
        if not scheme:
            raise TypeError("UserPartition dict {0} has unrecognized scheme {1}".format(value, scheme_id))

        if getattr(scheme, 'read_only', False):
            raise ReadOnlyUserPartitionError("UserPartition dict {0} uses scheme {1} which is read only".format(value, scheme_id))

        if hasattr(scheme, "create_user_partition"):
            return scheme.create_user_partition(
                value["id"],
                value["name"],
                value["description"],
                groups,
                parameters,
                active,
            )
        else:
            return UserPartition(
                value["id"],
                value["name"],
                value["description"],
                groups,
                scheme,
                parameters,
                active,
            )

    def get_group(self, group_id):
        """
        Returns the group with the specified id.

        Arguments:
            group_id (int): ID of the partition group.

        Raises:
            NoSuchUserPartitionGroupError: The specified group could not be found.

        """
        for group in self.groups:
            if group.id == group_id:
                return group

        raise NoSuchUserPartitionGroupError(
            "Could not find a Group with ID [{group_id}] in UserPartition [{partition_id}].".format(
                group_id=group_id, partition_id=self.id
            )
        )

    def access_denied_message(self, block, user, user_group, allowed_groups):
        """
        Return a message that should be displayed to the user when they are not allowed to access
        content managed by this partition, or None if there is no applicable message.

        Arguments:
            block (:class:`.XBlock`): The content being managed
            user (:class:`.User`): The user who was denied access
            user_group (:class:`.Group`): The current Group the user is in
            allowed_groups (list of :class:`.Group`): The groups who are allowed to see the content

        Returns: str
        """
        return None

    def access_denied_fragment(self, block, user, user_group, allowed_groups):
        """
        Return an html fragment that should be displayed to the user when they are not allowed to access
        content managed by this partition, or None if there is no applicable message.

        Arguments:
            block (:class:`.XBlock`): The content being managed
            user (:class:`.User`): The user who was denied access
            user_group (:class:`.Group`): The current Group the user is in
            allowed_groups (list of :class:`.Group`): The groups who are allowed to see the content

        Returns: :class:`.Fragment`
        """
        return None
