"""Stable JSON shapes for the API."""

import re

from rest_framework import serializers

from dashboard.models import Pool


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            raise serializers.ValidationError("必须是布尔值")
        return data


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = data.keys() - self.fields.keys()
            if unknown:
                raise serializers.ValidationError({key: ["不支持的字段"] for key in sorted(unknown)})
        return super().to_internal_value(data)


class StrictRevisionField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("必须是正整数")
        return super().to_internal_value(data)


class PoolControlsSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=("public", "private"), required=False)
    visibility = serializers.ChoiceField(choices=("public", "hidden"), required=False)
    expected_revision = StrictRevisionField(min_value=1, required=False)
    expected_rule_revision = StrictRevisionField(min_value=1, required=False)
    rarity_mapping = serializers.JSONField(required=False)
    clear_unmapped = StrictBooleanField(required=False)


class PoolCopySerializer(StrictSerializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=("public", "private"))
    expected_revision = StrictRevisionField(min_value=1)
    expected_source_rule_revision = StrictRevisionField(min_value=1)
    rule_ref = serializers.JSONField(required=False)
    expected_rule_revision = StrictRevisionField(min_value=1, required=False)
    rarity_mapping = serializers.JSONField(required=False)
    clear_unmapped = StrictBooleanField(required=False)


class RuleSerializer(StrictSerializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()
    visibility = serializers.CharField()
    owner_id = serializers.UUIDField(allow_null=True)
    owner_name = serializers.CharField(allow_null=True)
    original_author = serializers.CharField()
    algorithm = serializers.CharField()
    revision = serializers.IntegerField()
    document = serializers.JSONField()
    reference_count = serializers.IntegerField()
    structure_locked = serializers.BooleanField()

    def to_representation(self, rule):
        from dashboard.models import Pool
        from dashboard.services.rules import rule_document
        actor = self.context["actor"]
        refs = Pool.objects.filter(rule=rule)
        if not actor.is_superuser:
            from django.db.models import Q
            refs = refs.filter(Q(kind=Pool.PUBLIC) | Q(kind=Pool.PRIVATE, visibility=Pool.PUBLIC) |
                               Q(kind=Pool.PRIVATE, owner_id=actor.pk))
        return {"id": str(rule.pk), "name": rule.name, "kind": rule.kind,
                "visibility": rule.visibility,
                "owner_id": str(rule.owner_id) if rule.owner_id else None,
                "owner_name": rule.owner.username if rule.owner_id else None,
                "original_author": rule.original_author, "algorithm": rule.algorithm,
                "revision": rule.revision, "document": rule_document(rule),
                "reference_count": refs.count(), "structure_locked": rule.pools.exists()}


class PoolSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()
    visibility = serializers.CharField()
    owner_id = serializers.UUIDField(allow_null=True)
    owner_name = serializers.CharField(allow_null=True)
    original_author = serializers.CharField()
    rule_ref = serializers.JSONField()
    document = serializers.JSONField()
    revision = serializers.IntegerField()
    updated_at = serializers.DateTimeField()

    def to_representation(self, instance):
        from dashboard.services.pools import pool_document
        return {
            "id": str(instance.pk),
            "name": instance.name,
            "kind": instance.kind,
            "visibility": instance.visibility,
            "owner_id": str(instance.owner_id) if instance.owner_id else None,
            "owner_name": instance.owner.username if instance.owner_id else None,
            "original_author": instance.original_author,
            "rule_ref": {"id": str(instance.rule_id), "name": instance.rule.name,
                         "revision": instance.rule.revision},
            "document": pool_document(instance),
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


class BigPityParametersSerializer(StrictSerializer):
    target_obtained = StrictBooleanField()
    misses = DecimalCountField(minimum=0)


class ExperimentParametersSerializer(StrictSerializer):
    draws = DecimalCountField(minimum=1)
    trials = DecimalCountField(minimum=1)
    seed = DecimalSeedField(allow_null=True)
    trace = StrictBooleanField()
    initial_main_draws = DecimalCountField(minimum=0)
    initial_small_pity = serializers.DictField(child=DecimalCountField(minimum=0))
    initial_big_pity = BigPityParametersSerializer()


class ExperimentPoolReferenceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(max_length=255, trim_whitespace=True)


class ExperimentSaveSerializer(StrictSerializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    pool_ref = ExperimentPoolReferenceSerializer()
    parameters = ExperimentParametersSerializer()
    initial_context = serializers.JSONField(allow_null=True)
    expected_pool_revision = StrictRevisionField(min_value=1)
    expected_rule_revision = StrictRevisionField(min_value=1)
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentImportPreviewSerializer(StrictSerializer):
    document = serializers.JSONField()
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentImportConfirmSerializer(StrictSerializer):
    document = serializers.JSONField()
    pool_id = serializers.UUIDField()
    pool_revision = StrictRevisionField(min_value=1)
    rule_revision = StrictRevisionField(min_value=1)
    owner_id = serializers.UUIDField(required=False, write_only=True)


class ExperimentConfigSerializer(StrictSerializer):
    id = serializers.UUIDField()
    owner_id = serializers.UUIDField()
    owner_name = serializers.CharField()
    owner_is_admin = serializers.BooleanField()
    name = serializers.CharField()
    pool_ref = serializers.JSONField()
    parameters = ExperimentParametersSerializer()
    initial_context = serializers.JSONField()
    validation_errors = serializers.ListField(child=serializers.CharField())
    current_context = serializers.JSONField(allow_null=True)
    needs_confirmation = serializers.BooleanField()
    revision = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def to_representation(self, instance):
        from dashboard.services.experiments import experiment_validation
        actor = self.context.get("actor")
        pool = instance.pool if instance.pool_id else None
        pool_available = bool(pool and actor and (
            actor.is_superuser or pool.kind == Pool.PUBLIC or
            (pool.kind == Pool.PRIVATE and pool.visibility == Pool.PUBLIC) or
            (pool.kind == Pool.PRIVATE and pool.owner_id == actor.pk)
        ))
        params = instance.parameters_json
        api_parameters = dict(params)
        for field in ("draws", "trials", "initial_main_draws", "seed"):
            if type(api_parameters.get(field)) is int:
                api_parameters[field] = str(api_parameters[field])
        small = api_parameters.get("initial_small_pity")
        if isinstance(small, dict):
            api_parameters["initial_small_pity"] = {
                key: str(value) if type(value) is int else value for key, value in small.items()
            }
        big = api_parameters.get("initial_big_pity")
        if isinstance(big, dict) and type(big.get("misses")) is int:
            api_parameters["initial_big_pity"] = {**big, "misses": str(big["misses"])}
        diagnostics = (experiment_validation(instance) if pool_available else {
            "validation_errors": ["引用角色池当前不可用"],
            "current_context": None, "needs_confirmation": True,
        })
        return {
            "id": str(instance.pk),
            "owner_id": str(instance.owner_id),
            "owner_name": instance.owner.username,
            "owner_is_admin": instance.owner.is_superuser,
            "name": instance.name,
            "pool_ref": {"id": str(instance.pool_id) if instance.pool_id else None,
                         "name": pool.name if pool_available else instance.pool_name_hint,
                         "available": pool_available},
            "parameters": api_parameters,
            "initial_context": instance.initial_context_json,
            **diagnostics,
            "revision": instance.revision,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
