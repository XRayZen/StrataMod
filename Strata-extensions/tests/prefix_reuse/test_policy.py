import unittest
import reference


class PrefixPolicyTests(unittest.TestCase):
    def setUp(self):
        self.key = reference.Key('asset', 'bundle', 1, 4096, 'single', 'pci', None, (), None, 'canonical')

    def decide(self, **changes):
        args = dict(processed=[0, 12], mask=[0, 0], prompt=[0, 12, 34],
                    incoming_mask=[0, 0, 0], previous=self.key, incoming=self.key,
                    position=2, valid=True, logits=True, full_logits=False, reset=False)
        args.update(changes)
        return reference.decide(**args)

    def test_append_and_exact(self):
        self.assertEqual(self.decide(), ('append', 2))
        self.assertEqual(self.decide(prompt=[0, 12], incoming_mask=[0, 0]), ('logits', 2))

    def test_emitted_last_token_is_not_processed(self):
        # Emitted 34 at max/EOS has not yet advanced state, and belongs to suffix.
        self.assertEqual(self.decide()[1], 2)

    def test_branch_shortening_and_reset(self):
        for change in [dict(prompt=[0], incoming_mask=[0]),
                       dict(prompt=[0, 13, 34]), dict(reset=True)]:
            self.assertEqual(self.decide(**change)[0], 'fresh')

    def test_invalid_missing_logits_and_position(self):
        for change in [dict(valid=False), dict(logits=False), dict(position=3),
                       dict(full_logits=True), dict(processed=[], mask=[], position=0)]:
            self.assertEqual(self.decide(**change)[0], 'fresh')

    def test_mask_and_provenance(self):
        self.assertEqual(self.decide(incoming_mask=[0, 1, 0])[0], 'fresh')
        for field, value in [('epoch', 2), ('context', 8192), ('math', 'fast'),
                             ('bundle', 'other'), ('mode', 'expert-assist')]:
            key = reference.replace(self.key, **{field: value})
            self.assertEqual(self.decide(incoming=key)[0], 'fresh')

    def test_checked_domains(self):
        for change in [dict(prompt=[129280]), dict(prompt=[-1]),
                       dict(incoming_mask=[0]), dict(mask=[0]), dict(position=-1)]:
            with self.assertRaises(ValueError):
                self.decide(**change)

    def test_sampling_and_request_identity_are_not_math_keys(self):
        self.assertNotIn('request_id', self.key.__dataclass_fields__)
        self.assertNotIn('seed', self.key.__dataclass_fields__)
        self.assertNotIn('temperature', self.key.__dataclass_fields__)
        self.assertEqual(self.decide(), ('append', 2))

    def test_cursor_literal(self):
        self.assertEqual([n - 1 for n in [127, 128, 129]], [126, 127, 128])


if __name__ == '__main__':
    unittest.main()
