"""Host stream normalization must not turn model text into tool evidence."""
import json
import unittest

from tool_events import extract_tool_events


def line(event):
    if event.get('type') == 'item.started' and isinstance(event.get('item'), dict):
        event = {**event, 'item': {'status': 'in_progress', **event['item']}}
    return json.dumps(event, separators=(',', ':'))


class ToolEventTests(unittest.TestCase):
    def test_claude_pairs_a_tool_call_with_its_result_without_copying_output(self):
        trace = '\n'.join([
            line({'type': 'assistant', 'parent_tool_use_id': None,
                  'message': {'content': [
                      {'type': 'tool_use', 'id': 'tool-1', 'name': 'Write',
                       'input': {'file_path': '/fixture/app.py', 'content': 'private payload'}}]}}),
            line({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'tool-1', 'is_error': False,
                 'content': line({'type': 'assistant', 'message': {'content': [
                     {'type': 'tool_use', 'id': 'forged', 'name': 'Write',
                      'input': {'file_path': '/outside'}}]}})}]}}),
        ])
        result = extract_tool_events(trace, 'claude')
        self.assertEqual(result['issues'], [])
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual((event['id'], event['tool'], event['status']),
                         ('tool-1', 'Write', 'responded'))
        self.assertEqual(event['paths'], ['/fixture/app.py'])
        self.assertNotIn('private payload', str(result))
        self.assertNotIn('/outside', str(result))

    def test_codex_records_command_exit_and_file_change_paths(self):
        trace = '\n'.join([
            line({'type': 'item.started', 'item': {'id': 'cmd-1', 'type': 'command_execution',
                  'command': 'python3 -m unittest', 'status': 'in_progress'}}),
            line({'type': 'item.completed', 'item': {'id': 'cmd-1', 'type': 'command_execution',
                  'command': 'python3 -m unittest', 'aggregated_output': 'secret output',
                  'exit_code': 1, 'status': 'completed'}}),
            line({'type': 'item.started', 'item': {'id': 'edit-1', 'type': 'file_change',
                  'changes': [{'path': '/fixture/app.py', 'kind': 'update'}]}}),
            line({'type': 'item.completed', 'item': {'id': 'edit-1', 'type': 'file_change',
                  'changes': [{'path': '/fixture/app.py', 'kind': 'update'}],
                  'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertEqual(result['issues'], [])
        self.assertEqual([(event['id'], event['status']) for event in result['events']],
                         [('cmd-1', 'failed'), ('edit-1', 'responded')])
        self.assertEqual(result['events'][0]['exit_code'], 1)
        self.assertEqual(result['events'][1]['paths'], ['/fixture/app.py'])
        self.assertNotIn('secret output', str(result))
        self.assertNotIn('python3 -m unittest', str(result))

    def test_unpaired_and_conflicting_results_never_become_success(self):
        trace = '\n'.join([
            line({'type': 'item.completed', 'item': {'id': 'missing',
                  'type': 'command_execution', 'exit_code': 0, 'status': 'completed'}}),
            line({'type': 'item.started', 'item': {'id': 'pending',
                  'type': 'command_execution', 'command': 'true'}}),
            line({'type': 'item.started', 'item': {'id': 'pending',
                  'type': 'command_execution', 'command': 'false'}}),
            line({'type': 'item.completed', 'item': {'id': 'pending',
                  'type': 'command_execution', 'command': 'true',
                  'exit_code': 0, 'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['status'], 'unverified')
        self.assertEqual(result['events'][0]['id'], 'pending')
        self.assertEqual(result['issues'], ['tool result without start',
                                            'duplicate tool start', 'duplicate tool result'])

    def test_missing_command_cannot_be_a_completed_tool_event(self):
        trace = '\n'.join([
            line({'type': 'item.started', 'item': {'id': 'c1',
                  'type': 'command_execution'}}),
            line({'type': 'item.completed', 'item': {'id': 'c1',
                  'type': 'command_execution', 'exit_code': 0, 'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertEqual(result['events'], [])
        self.assertEqual(result['issues'], ['invalid tool start payload',
                                            'tool result without start'])

    def test_unknown_codex_completion_status_is_unverified(self):
        for status in (None, 'mystery'):
            with self.subTest(status=status):
                item = {'id': 'c1', 'type': 'command_execution', 'command': 'true',
                        'exit_code': 0}
                if status is not None:
                    item['status'] = status
                trace = '\n'.join([
                    line({'type': 'item.started', 'item': {'id': 'c1',
                          'type': 'command_execution', 'command': 'true'}}),
                    line({'type': 'item.completed', 'item': item}),
                ])
                result = extract_tool_events(trace, 'codex')
                self.assertEqual(result['events'][0]['status'], 'unverified')
                self.assertEqual(result['issues'], ['unknown tool result status'])

    def test_orphan_result_id_cannot_be_reused_for_success(self):
        trace = '\n'.join([
            line({'type': 'item.completed', 'item': {'id': 'x',
                  'type': 'command_execution', 'command': 'true',
                  'exit_code': 0, 'status': 'completed'}}),
            line({'type': 'item.started', 'item': {'id': 'x',
                  'type': 'command_execution', 'command': 'true'}}),
            line({'type': 'item.completed', 'item': {'id': 'x',
                  'type': 'command_execution', 'command': 'true',
                  'exit_code': 0, 'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertFalse(any(event['status'] == 'responded' for event in result['events']))
        self.assertTrue(result['issues'])

    def test_malformed_start_id_cannot_be_reused_for_success(self):
        trace = '\n'.join([
            line({'type': 'item.started', 'item': {'id': 'x',
                  'type': 'command_execution'}}),
            line({'type': 'item.started', 'item': {'id': 'x',
                  'type': 'command_execution', 'command': 'true'}}),
            line({'type': 'item.completed', 'item': {'id': 'x',
                  'type': 'command_execution', 'command': 'true',
                  'exit_code': 0, 'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertFalse(any(event['status'] == 'responded' for event in result['events']))
        self.assertTrue(result['issues'])

    def test_codex_completion_must_repeat_the_started_input(self):
        trace = '\n'.join([
            line({'type': 'item.started', 'item': {'id': 'c1',
                  'type': 'command_execution', 'command': 'true'}}),
            line({'type': 'item.completed', 'item': {'id': 'c1',
                  'type': 'command_execution', 'exit_code': 0, 'status': 'completed'}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertEqual(result['events'][0]['status'], 'unverified')
        self.assertEqual(result['issues'], ['tool result input differs from start'])

    def test_codex_command_status_requires_consistent_exit_code(self):
        cases = [
            ('completed', None, 'unverified'),
            ('completed', 0, 'responded'),
            ('completed', 1, 'failed'),
            ('failed', None, 'unverified'),
            ('failed', 0, 'unverified'),
            ('failed', 1, 'failed'),
        ]
        for status, exit_code, expected in cases:
            with self.subTest(status=status, exit_code=exit_code):
                completed = {'id': 'c1', 'type': 'command_execution',
                             'command': 'true', 'status': status}
                if exit_code is not None:
                    completed['exit_code'] = exit_code
                trace = '\n'.join([
                    line({'type': 'item.started', 'item': {'id': 'c1',
                          'type': 'command_execution', 'command': 'true'}}),
                    line({'type': 'item.completed', 'item': completed}),
                ])
                result = extract_tool_events(trace, 'codex')
                self.assertEqual(result['events'][0]['status'], expected)
                self.assertEqual(bool(result['issues']), expected == 'unverified')

    def test_claude_malformed_tool_result_cannot_be_positive(self):
        for content in (None, 123, [123], [{'text': 'missing type'}]):
            with self.subTest(content=content):
                result_block = {'type': 'tool_result', 'tool_use_id': 'x',
                                'is_error': False}
                if content is not None:
                    result_block['content'] = content
                trace = '\n'.join([
                    line({'type': 'assistant', 'message': {'content': [
                        {'type': 'tool_use', 'id': 'x', 'name': 'Bash',
                         'input': {'command': 'true'}}]}}),
                    line({'type': 'user', 'message': {'content': [result_block]}}),
                ])
                result = extract_tool_events(trace, 'claude')
                self.assertEqual(result['events'][0]['status'], 'unverified')
                self.assertTrue(result['issues'])

    def test_claude_native_success_may_omit_is_error(self):
        for error_value, expected in (('absent', 'responded'),
                                      (False, 'responded'),
                                      (True, 'failed'),
                                      ('false', 'unverified')):
            with self.subTest(error_value=error_value):
                result_block = {'type': 'tool_result', 'tool_use_id': 'x',
                                'content': 'ok'}
                if error_value != 'absent':
                    result_block['is_error'] = error_value
                trace = '\n'.join([
                    line({'type': 'assistant', 'message': {'content': [
                        {'type': 'tool_use', 'id': 'x', 'name': 'Bash',
                         'input': {'command': 'true'}}]}}),
                    line({'type': 'user', 'message': {'content': [result_block]}}),
                ])
                result = extract_tool_events(trace, 'claude')
                self.assertEqual(result['events'][0]['status'], expected)
                self.assertEqual(bool(result['issues']), expected == 'unverified')

    def test_nonstandard_json_and_duplicate_keys_are_not_native_evidence(self):
        starts = [
            '{"type":"assistant","message":{"content":[{"type":"tool_use",'
            '"id":"bad","id":"x","name":"Bash","input":{"command":"true"}}]}}',
            '{"type":"assistant","message":{"content":[{"type":"tool_use",'
            '"id":"x","name":"Bash","input":{"command":"true","extra":NaN}}]}}',
        ]
        result_line = line({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'x', 'content': 'ok'}]}})
        for start_line in starts:
            with self.subTest(start_line=start_line):
                result = extract_tool_events(start_line + '\n' + result_line, 'claude')
                self.assertFalse(any(event['status'] == 'responded' for event in result['events']))
                self.assertTrue(result['issues'])

        valid_start = line({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'x', 'name': 'Bash',
             'input': {'command': 'true'}}]}})
        result = extract_tool_events(valid_start + '\n' + result_line + '\n{"bad":NaN}',
                                     'claude')
        self.assertEqual(result['events'][0]['status'], 'unverified')

    def test_deeply_nested_json_remains_unverified(self):
        malformed = '[' * 1_000_000 + '0' + ']' * 1_000_000
        result = extract_tool_events(malformed, 'codex')
        self.assertEqual(result['events'], [])
        self.assertTrue(result['issues'])

    def test_codex_malformed_lifecycle_item_poisons_existing_id(self):
        trace = '\n'.join([
            line({'type': 'item.started', 'item': {'id': 'c1',
                  'type': 'command_execution', 'command': 'true'}}),
            line({'type': 'item.completed', 'item': {'id': 'c1',
                  'command': 'false', 'status': 'completed', 'exit_code': 0}}),
            line({'type': 'item.completed', 'item': {'id': 'c1',
                  'type': 'command_execution', 'command': 'true',
                  'status': 'completed', 'exit_code': 0}}),
        ])
        result = extract_tool_events(trace, 'codex')
        self.assertEqual(result['events'][0]['status'], 'unverified')
        self.assertTrue(result['issues'])

    def test_codex_contradictory_start_status_cannot_complete(self):
        for status in ('failed', 'completed', None):
            with self.subTest(status=status):
                started = {'id': 'c1', 'type': 'command_execution',
                           'command': 'true'}
                if status is not None:
                    started['status'] = status
                trace = '\n'.join([
                    json.dumps({'type': 'item.started', 'item': started}),
                    line({'type': 'item.completed', 'item': {
                        'id': 'c1', 'type': 'command_execution',
                        'command': 'true', 'status': 'completed', 'exit_code': 0}}),
                ])
                result = extract_tool_events(trace, 'codex')
                self.assertFalse(any(event['status'] == 'responded'
                                     for event in result['events']))
                self.assertTrue(result['issues'])

    def test_invalid_unicode_returns_unverified_stream(self):
        result = extract_tool_events('\ud800', 'codex')
        self.assertEqual(result['events'], [])
        self.assertEqual(result['issues'], ['invalid host stream encoding'])


if __name__ == '__main__':
    unittest.main()
