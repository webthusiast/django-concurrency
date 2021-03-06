from django import forms
from django.core import validators
from django.core.exceptions import NON_FIELD_ERRORS, SuspiciousOperation
from django.core.signing import Signer, BadSignature
from django.forms import ModelForm, HiddenInput
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _
from concurrency.core import _select_lock, RecordModifiedError


class ConcurrentForm(ModelForm):
    """ Simple wrapper to ModelForm that try to mitigate some concurrency error.
        Note that is always possible have a RecordModifiedError in model.save().
        Statistically form.clean() should catch most of the concurrent editing, but
        is good to catch RecordModifiedError in the view too.
    """

    def clean(self):
        try:
            _select_lock(self.instance, self.cleaned_data[self.instance.RevisionMetaInfo.field.name])
        except RecordModifiedError:
            self._update_errors({NON_FIELD_ERRORS: self.error_class([_('Record Modified')])})

        return super(ConcurrentForm, self).clean()

    def save(self, commit=True):
        return super(ConcurrentForm, self).save(commit)


class VersionWidget(HiddenInput):
    """
    Widget that show the revision number using <div>

    Usually VersionField use `HiddenInput` as Widget to minimize the impact on the
    forms, in the Admin this produce a side effect to have the label *Version* without
    any value, you should use this widget to display the current revision number
    """

    def _format_value(self, value):
        if value:
            value = str(value)
        return value

    def render(self, name, value, attrs=None):
        ret = super(VersionWidget, self).render(name, value, attrs)
        if value is None:
            value = ''
        return mark_safe("%s<div>%s</div>" % (ret, value))


class VersionFieldSigner(Signer):
    pass


class SignedValue(object):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        if self.value:
            return str(self.value)
        else:
            return ''


class VersionField(forms.IntegerField):
    widget = HiddenInput # Default widget to use when rendering this type of Field.
    hidden_widget = HiddenInput# Default widget to use when rendering this as "hidden".

    def __init__(self, *args, **kwargs):
        self._signer = kwargs.pop('signer', VersionFieldSigner())
        kwargs.pop('min_value', None)
        kwargs.pop('max_value', None)
        kwargs['required'] = True
        kwargs['initial'] = None
        kwargs.setdefault('widget', HiddenInput)
        super(VersionField, self).__init__(*args, **kwargs)

    def bound_data(self, data, initial):
        return SignedValue(data)

    def prepare_value(self, value):
        if isinstance(value, SignedValue):
            return value
        return SignedValue(self._signer.sign(value))

    def to_python(self, value):
        try:
            if value not in (None, '', 'None'):
                return int(self._signer.unsign(value))
            return 0
        except (BadSignature, ValueError):
            raise SuspiciousOperation(_('Version number seems tampered'))

    def widget_attrs(self, widget):
        return {}


class DateVersionField(forms.DateTimeField):
    widget = HiddenInput # Default widget to use when rendering this type of Field.
    hidden_widget = HiddenInput # Default widget to use when rendering this as "hidden".

    def __init__(self, *args, **kwargs):
        kwargs.pop('input_formats', None)
        kwargs['required'] = True
        kwargs['initial'] = None
        kwargs['widget'] = None
        super(DateVersionField, self).__init__(None, *args, **kwargs)

    def to_python(self, value):
        value = super(DateVersionField, self).to_python(value)
        if value in validators.EMPTY_VALUES:
            return timezone.now()
        return value

    def widget_attrs(self, widget):
        return {}

