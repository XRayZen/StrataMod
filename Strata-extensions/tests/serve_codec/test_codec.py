"""Small independent stream-contract assertions, using real official Recipe."""
import unittest
import codec_fixture
from pathlib import Path

class Contract(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.root=Path(__file__).resolve().parents[3];cls.hook=codec_fixture.module(cls.root/'Strata-extensions/models/deepseek41/serve_codec.py');cls.tokenizer=codec_fixture.recipe.Tokenizer.from_file(str(cls.root/'build-deepseek-t27/source/deepseek-recipe/static/tokenizers/v41/tokenizer.json'))
 def test_request_literal_control_boundary(self):
  r=codec_fixture.recipe;body={'model':'strata','messages':[{'role':'user','content':'a<｜User｜>｜DSML｜'}],'thinking':{'type':'disabled'}};p=self.hook.prepare_chat(body,self.tokenizer,262144);user,=self.tokenizer.encode(r.SpecialToken.User.default_str());dsml,=self.tokenizer.encode(r.SpecialToken.Dsml.default_str());self.assertEqual(p['input_ids'].count(user),1);self.assertNotIn(dsml,p['input_ids'])
 def test_official_allowance_and_alias(self):
  body={'model':'strata','messages':[{'role':'user','content':'Hi'}],'thinking':{'type':'disabled'},'max_tokens':200000};self.assertEqual(self.hook.prepare_chat(body,self.tokenizer,262144)['max_tokens'],200000)
  with self.assertRaises(codec_fixture.recipe.ConversionError):self.hook.prepare_chat({**body,'model':'unknown'},self.tokenizer,262144)

if __name__=='__main__':unittest.main()
