"""Read-only original RefImage inputs; no generated image fixture or GPU."""
import unittest
from unittest.mock import patch
from local_runtime import image_phase as image,manifest,standalone_phase as phase


class RefImageTests(unittest.TestCase):
    def test_api_and_webui_keep_separate_original_inputs_and_prebound_rubrics(self):
        from tools.vision.image_api_cases import PROMPT
        from pathlib import Path
        self.assertEqual(image.API_BINDING.name,'image-api-refimage-v1-binding.json')
        expected={'expected_api07':{'scene':['fixture-a']},'expected_webui484':{'scene':['fixture-b']}}
        self.assertEqual(expected['expected_api07']['scene'][0],'fixture-a')
        self.assertEqual(expected['expected_webui484']['scene'][0],'fixture-b')
        value=image.webui_input(manifest.LOCAL/'records/refimage-unit')
        self.assertEqual(value['image_path'],str(image.FIXTURES/'48463779.jpeg'))
        self.assertEqual(value['image_sha256'],image.IMAGES[1][2])
        self.assertEqual(value['prompt'],PROMPT)
        self.assertNotIn('教室',PROMPT)
        self.assertNotIn('寝室',PROMPT)

    def test_exact_original_inputs_and_six_encoder_commands(self):
        self.assertEqual(len(image.IMAGES),2)
        rows=image.encode_protocol()
        self.assertEqual(sum(len(row['encodes']) for row in rows),6)
        self.assertEqual(manifest.SUITES['vision-encode']['max_encodes'],6)
        paths=[case['path'] for case in rows[0]['encodes']]
        self.assertEqual(paths,[str(image.FIXTURES/'07.png'),str(image.FIXTURES/'48463779.jpeg')])
        self.assertEqual([case['sha256'] for case in rows[0]['encodes']],
                         ['b3d0707f0812a413c9f8e017bcd40452fac7136174498db5c5d3b3e995c3b759',
                          '1806c40d735545d6852e1d1a90dba9c22f4501e79e9cb5784f93268e2331d699'])

    def test_selected_portraits_are_not_rejected_for_missing_generated_grid_coverage(self):
        def arm(index):
            return dict(images=[dict(name=name,output=f'{index}-{name}',valid=True,shape=[252,12,21,2560]) for name,_,_ in image.IMAGES],
                        stderr='GRAPH phase=warmup completed_hip_compute=1 completed_cpu_compute=1\n'+
                               'GRAPH phase=encode completed_hip_compute=2 completed_cpu_compute=1\n'*2,
                        memory_samples=[dict(label='after',gpu={key:1 for key in (
                            'adapter_dedicated_bytes','adapter_shared_bytes','process_dedicated_bytes','process_shared_bytes')})])
        result=dict(arms=[arm(i) for i in range(3)])
        with patch.object(image,'read_sve',return_value={}),patch.object(image,'compare_sve',return_value={'passed':True}):
            phase.encode_result({},result)
        self.assertTrue(result['coverage_passed'])
        self.assertFalse(result['coverage']['landscape_proved'])
        self.assertFalse(result['coverage']['exact_300_tokens_proved'])


if __name__=='__main__':unittest.main()
