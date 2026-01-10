"""Counter API Plugin - provides REST endpoints for counter operations."""

import json
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.plugin_system.oc_plugin import OCPlugin
from plugin.counter.models import CounterLog


class CounterOCPlugin(OCPlugin):
    """
    Example plugin that provides counter functionality via API.

    Endpoints:
    - GET    /api/plugins/counter/        - Get current counter value
    - POST   /api/plugins/counter/increment - Increment counter
    - POST   /api/plugins/counter/decrement - Decrement counter
    - POST   /api/plugins/counter/reset    - Reset counter to 0
    - GET    /api/plugins/counter/history  - Get counter history
    - DELETE /api/plugins/counter/history  - Clear history
    """

    @property
    def plugin_name(self):
        return "counter"

    def get_urls(self):
        return [
            path('', self.get_counter, name='get_counter'),
            path('increment', self.increment, name='increment'),
            path('decrement', self.decrement, name='decrement'),
            path('reset', self.reset, name='reset'),
            path('history', self.get_history, name='history'),
            path('history/clear', self.clear_history, name='clear_history'),
        ]

    def _get_current_value(self):
        """Get the current counter value from the latest log entry."""
        latest = CounterLog.objects.first()
        return latest.value if latest else 0

    @require_http_methods(["GET"])
    def get_counter(self, request):
        """GET /api/plugins/counter/ - Get current counter value."""
        try:
            current_value = self._get_current_value()
            total_actions = CounterLog.objects.count()

            return JsonResponse({
                'value': current_value,
                'total_actions': total_actions
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    @csrf_exempt
    @require_http_methods(["POST"])
    def increment(self, request):
        """POST /api/plugins/counter/increment - Increment counter by 1."""
        try:
            data = json.loads(request.body) if request.body else {}
            comment = data.get('comment', '')

            current_value = self._get_current_value()
            new_value = current_value + 1

            CounterLog.objects.create(
                action='INCREMENT',
                value=new_value,
                comment=comment
            )

            return JsonResponse({
                'action': 'INCREMENT',
                'previous_value': current_value,
                'new_value': new_value
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    @csrf_exempt
    @require_http_methods(["POST"])
    def decrement(self, request):
        """POST /api/plugins/counter/decrement - Decrement counter by 1."""
        try:
            data = json.loads(request.body) if request.body else {}
            comment = data.get('comment', '')

            current_value = self._get_current_value()
            new_value = current_value - 1

            CounterLog.objects.create(
                action='DECREMENT',
                value=new_value,
                comment=comment
            )

            return JsonResponse({
                'action': 'DECREMENT',
                'previous_value': current_value,
                'new_value': new_value
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    @csrf_exempt
    @require_http_methods(["POST"])
    def reset(self, request):
        """POST /api/plugins/counter/reset - Reset counter to 0."""
        try:
            data = json.loads(request.body) if request.body else {}
            comment = data.get('comment', 'Counter reset')

            current_value = self._get_current_value()

            CounterLog.objects.create(
                action='RESET',
                value=0,
                comment=comment
            )

            return JsonResponse({
                'action': 'RESET',
                'previous_value': current_value,
                'new_value': 0
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    @require_http_methods(["GET"])
    def get_history(self, request):
        """GET /api/plugins/counter/history - Get counter action history."""
        try:
            limit = int(request.GET.get('limit', 50))
            logs = CounterLog.objects.all()[:limit]

            history = [
                {
                    'id': log.id,
                    'action': log.action,
                    'value': log.value,
                    'comment': log.comment,
                    'timestamp': log.timestamp.isoformat()
                }
                for log in logs
            ]

            return JsonResponse({
                'count': len(history),
                'history': history
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    @csrf_exempt
    @require_http_methods(["DELETE"])
    def clear_history(self, request):
        """DELETE /api/plugins/counter/history/clear - Clear all counter history."""
        try:
            count = CounterLog.objects.count()
            CounterLog.objects.all().delete()

            return JsonResponse({
                'message': f'Cleared {count} history entries',
                'deleted_count': count
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
