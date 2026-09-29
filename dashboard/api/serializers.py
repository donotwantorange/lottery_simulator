"""Stable JSON shapes for the API."""

import re

from rest_framework import serializers

from dashboard.models import Pool


class StrictRevisionField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("必须是正整数")
        return super().to_internal_value(data)


class PoolControlsSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("public", "private"), required=False)
    visibility = serializers.ChoiceField(choices=("public", "hidden"), required=False)
    expected_revision = StrictRevisionField(min_value=1, required=False)


class PoolCopySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=("public", "private"))


class PoolSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()
    visibility = serializers.CharField()
    owner_id = serializers.UUIDField(allow_null=True)
    owner_name = serializers.CharField(allow_null=True)
    original_author = serializers.CharField()
    rule_name = serializers.CharField()
    rarity_labels = serializers.JSONField()
    pool_config = serializers.JSONField()
    revision = serializers.IntegerField()
    updated_at = serializers.DateTimeField()

    def to_representation(self, instance):
        return {
            "id": str(instance.pk),
            "name": instance.name,
            "kind": instance.kind,
            "visibility": instance.visibility,
            "owner_id": str(instance.owner_id) if instance.owner_id else None,
            "owner_name": instance.owner.username if instance.owner_id else None,
            "original_author": instance.original_author,
            "rule_name": instance.rule_name,
            "rarity_labels": instance.config_json.get("rarity_labels", {}),
            "pool_config": {key: value for key, value in instance.config_json.items()
                            if key not in {"format_version", "rarity_labels"}},
            "revision": instance.revision,
            "updated_at": instance.updated_at,
        }


class DecimalCountField(serializers.Field):
    """Keep browser counts as decimal strings while validating Python integers."""

    def __init__(self, *, minimum, **kwargs):
        self.minimum = minimum
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str) and re.fullmatch(r"(0|[1-9][0-9]*)", data):
            try:
                value = int(data)
            except ValueError:
                raise serializers.ValidationError("整数过长") from None
        elif type(data) is int and abs(data) <= 9007199254740991:
            value = data
        else:
            raise serializers.ValidationError("必须是十进制整数字符串")
        if value < self.minimum:
            raise serializers.ValidationError(f"必须不小于{self.minimum}")
        return value

    def to_representation(self, value):
        return str(value)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            raise serializers.ValidationError("必须是布尔值")
        return data


class DecimalSeedField(serializers.Field):
    """Transfer arbitrary-size seeds without JavaScript number rounding."""

    default_error_messages = {"invalid": "随机种子必须是十进制整数或null"}

    def to_internal_value(self, data):
        if data is None:
            return None
        if isinstance(data, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", data):
            try:
                return int(data)
            except ValueError:
                self.fail("invalid")
        if type(data) is int and abs(data) <= 9007199254740991:
            return data
        self.fail("invalid")

    def to_representation(self, value):
        return None if value is None else str(value)


class ExperimentParametersSerializer(serializers.Serializer):
    draws = DecimalCountField(minimum=1)
    trials = DecimalCountField(minimum=1)
    initial_pity = DecimalCountField(minimum=0)
    initial_five_star_pity = DecimalCountField(minimum=0)
    seed = DecimalSeedField(allow_null=True)
    trace = StrictBooleanField()


class ExperimentPoolReferenceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(max_length=255, trim_whitespace=True)


class ExperimentSaveSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    pool_ref = ExperimentPoolReferenceSerializer()
    parameters = ExperimentParametersSerializer()
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentImportPreviewSerializer(serializers.Serializer):
    document = serializers.JSONField()
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentImportConfirmSerializer(serializers.Serializer):
    document = serializers.JSONField()
    pool_id = serializers.UUIDField()
    pool_revision = StrictRevisionField(min_value=1)
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentConfigSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.UUIDField()
    owner_name = serializers.CharField()
    owner_is_admin = serializers.BooleanField()
    name = serializers.CharField()
    pool_ref = serializers.JSONField()
    parameters = ExperimentParametersSerializer()
    revision = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def to_representation(self, instance):
        actor = self.context.get("actor")
        pool = instance.pool if instance.pool_id else None
        pool_available = bool(pool and actor and (
            actor.is_superuser or pool.kind == Pool.PUBLIC or
            (pool.kind == Pool.PRIVATE and pool.visibility == Pool.PUBLIC) or
            (pool.kind == Pool.PRIVATE and pool.owner_id == actor.pk)
        ))
        return {
            "id": str(instance.pk),
            "owner_id": str(instance.owner_id),
            "owner_name": instance.owner.username,
            "owner_is_admin": instance.owner.is_superuser,
            "name": instance.name,
            "pool_ref": {"id": str(instance.pool_id) if instance.pool_id else None,
                         "name": pool.name if pool_available else instance.pool_name_hint,
                         "available": pool_available},
            "parameters": ExperimentParametersSerializer(instance.parameters_json).data,
            "revision": instance.revision,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
