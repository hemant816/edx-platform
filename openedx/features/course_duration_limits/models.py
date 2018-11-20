"""
Course Duration Limit Configuration Models
"""

# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import ugettext_lazy as _

from student.models import CourseEnrollment
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.config_model_utils.models import StackedConfigurationModel
from openedx.features.course_duration_limits.config import CONTENT_TYPE_GATING_FLAG


class CourseDurationLimitConfig(StackedConfigurationModel):

    STACKABLE_FIELDS = ('enabled', 'enabled_as_of')

    enabled_as_of = models.DateField(
        default=None,
        null=True,
        verbose_name=_('Enabled As Of'),
        blank=True,
        help_text=_('If the configuration is Enabled, then all enrollments created after this date (UTC) will be affected.')
    )

    @classmethod
    def enabled_for_enrollment(cls, enrollment=None, user=None, course_key=None):
        """
        Return whether Course Duration Limits are enabled for this enrollment.

        Course Duration Limits are enabled for an enrollment if they are enabled for
        the course being enrolled in (either specifically, or via a containing context,
        such as the org, site, or globally), and if the configuration is specified to be
        ``enabled_as_of`` before the enrollment was created.

        Only one of enrollment and (user, course_key) may be specified at a time.

        Arguments:
            enrollment: The enrollment being queried.
            user: The user being queried.
            course_key: The CourseKey of the course being queried.
        """
        if CONTENT_TYPE_GATING_FLAG.is_enabled():
            return True

        if enrollment is not None and (user is not None or course_key is not None):
            raise ValueError('Specify enrollment or user/course_key, but not both')

        if enrollment is None and (user is None or course_key is None):
            raise ValueError('Both user and course_key must be specified if no enrollment is provided')

        if enrollment is None and user is None and course_key is None:
            raise ValueError('At least one of enrollment or user and course_key must be specified')

        if course_key is None:
            course_key = enrollment.course_id

        if enrollment is None:
            enrollment = CourseEnrollment.get_enrollment(user, course_key)

        # enrollment might be None if the user isn't enrolled. In that case,
        # return enablement as if the user enrolled today
        if enrollment is None:
            return cls.enabled_for_course(course_key=course_key, target_date=datetime.utcnow().date())
        else:
            current_config = cls.current(course_key=enrollment.course_id)
            return current_config.enabled_as_of_date(target_date=enrollment.created.date())

    @classmethod
    def enabled_for_course(cls, course_key, target_date=None):
        """
        Return whether Course Duration Limits are enabled for this course as of a particular date.

        Course Duration Limits are enabled for a course on a date if they are enabled either specifically,
        or via a containing context, such as the org, site, or globally, and if the configuration
        is specified to be ``enabled_as_of`` before ``target_date``.

        Only one of enrollment and (user, course_key) may be specified at a time.

        Arguments:
            course_key: The CourseKey of the course being queried.
            target_date: The date to checked enablement as of. Defaults to the current date.
        """
        if CONTENT_TYPE_GATING_FLAG.is_enabled():
            return True

        if target_date is None:
            target_date = datetime.utcnow().date()

        current_config = cls.current(course_key=course_key)
        return current_config.enabled_as_of_date(target_date=target_date)

    def clean(self):
        if self.enabled and self.enabled_as_of is None:
            raise ValidationError({'enabled_as_of': _('enabled_as_of must be set when enabled is True')})

    def enabled_as_of_date(self, target_date):
        if CONTENT_TYPE_GATING_FLAG.is_enabled():
            return True

        # Explicitly cast this to bool, so that when self.enabled is None the method doesn't return None
        return bool(self.enabled and self.enabled_as_of <= target_date)
