from repESP.types import *
from repESP.charges import *
from repESP.esp_util import GaussianEspData, parse_gaussian_esp
from repESP.esp_util import EspData, parse_resp_esp, write_resp_esp
from repESP.fields import *

from my_unittest import TestCase

from io import StringIO


gaussian_esp_data = GaussianEspData(
    0,
    1,
    Molecule([
        AtomWithCoordsAndCharge(
            6,
            Coords((0, 0, 0)),
            Charge(-0.50031415)
        ),
        AtomWithCoordsAndCharge(
            1,
            Coords((1.23, 0.456, 0.0789)),
            Charge( 0.12532268)
        )
    ]),
    DipoleMoment(
        DipoleMomentValue( 0.38811727e-15),
        DipoleMomentValue( 0.42690461e-16),
        DipoleMomentValue(-0.29029513e-15)
    ),
    QuadrupoleMoment(
        QuadrupoleMomentValue(-0.26645353e-14),
        QuadrupoleMomentValue( 0.35527137e-14),
        QuadrupoleMomentValue(-0.88817842e-15),
        QuadrupoleMomentValue(-0.13868301e-15),
        QuadrupoleMomentValue(-0.97158067e-16),
        QuadrupoleMomentValue( 0.72144168e-15),
    ),
    Field(
        Mesh(
            [
                Coords(( 0.00000000,  0.0000000, 3.9684249)),
                Coords((-0.99210622,  1.7183784, 3.4367568)),
                Coords(( 0.99210622, -1.7183784, 3.4367568))
            ],
        ),
        [
            Esp(-0.26293556e-2),
            Esp(-0.28665426e-2),
            Esp(-0.28665426e-2)
        ]
    )
)


class TestGaussianEsp(TestCase):

    def test_parsing(self) -> None:

        with open("tests/test_gaussian.esp") as f:
            parsed_gaussian_esp_data = parse_gaussian_esp(f)

        self.assertAlmostEqualRecursive(
            gaussian_esp_data,
            parsed_gaussian_esp_data
        )


class TestRespEsp(TestCase):

    def test_writing(self) -> None:

        esp_data = EspData.from_gaussian(gaussian_esp_data)

        written = StringIO()
        write_resp_esp(written, esp_data)
        written.seek(0)

        with open("tests/test_resp.esp") as f:
            self.assertListEqual(f.readlines(), written.readlines())

    def test_parsing(self) -> None:

        with open("tests/test_resp.esp") as f:
            esp_data = parse_resp_esp(f)

        expected_esp_data = EspData.from_gaussian(gaussian_esp_data)

        self.assertAlmostEqualRecursive(
            esp_data,
            expected_esp_data,
            places=6
        )
