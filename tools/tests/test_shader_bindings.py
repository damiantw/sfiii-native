"""Invented shader declarations validate the SDL Metal resource contract."""
import importlib.util
import itertools
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('portable_package',Path(__file__).resolve().parents[1]/'package-posix.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


class ShaderBindings(unittest.TestCase):
    def test_uniform_and_storage_slots_cannot_be_permuted(self):
        for uniform,scene,textures in itertools.permutations(range(3)):
            code=(f'fragment fragmentMain(constant Params& Pass [[buffer({uniform})]], '
                  f'device Words& scene [[buffer({scene})]], device Words& textures [[buffer({textures})]], '
                  'texture2d<float> picture [[texture(0)]], sampler picture_sampler [[sampler(0)]]) {}')
            with self.subTest(slots=(uniform,scene,textures)):
                if (uniform,scene,textures)==(0,1,2):package.validate_metal_bindings(code,'geometry')
                else:
                    with self.assertRaises(ValueError):package.validate_metal_bindings(code,'geometry')

    def test_legacy_shader_without_uniform_keeps_automatic_slots(self):
        self.assertEqual(package.metal_binding_flags('geometry'),['--msl-decoration-binding'])
        self.assertEqual(package.metal_binding_flags('hd-assets'),[])
        package.validate_metal_bindings('fragment fragmentMain(device Words& scene [[buffer(0)]], device Words& art [[buffer(1)]]) {}','hd-assets')


if __name__=='__main__':unittest.main()
