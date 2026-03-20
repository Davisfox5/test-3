"""Resolve a Virginia address to the appropriate circuit court.

Virginia has 120 circuit courts (one per county and independent city).  This
module maps a petitioner's county/city to the court that has jurisdiction over
their name-change petition per Va. Code § 8.01-217.
"""

from __future__ import annotations

from va_name_change.models import Address, CircuitCourt

# ---------------------------------------------------------------------------
# Partial registry — in production this would be backed by a database or the
# Virginia Judicial System's public API.  The entries below cover a
# representative sample; extend as needed.
# ---------------------------------------------------------------------------

_COURT_REGISTRY: dict[str, CircuitCourt] = {
    "fairfax": CircuitCourt(
        name="Fairfax County Circuit Court",
        fips_code="059",
        address=Address(
            street="4110 Chain Bridge Rd",
            city="Fairfax",
            zip_code="22030",
            county="Fairfax",
        ),
        phone="(703) 246-2772",
        filing_fee_usd=53.00,
        vjefs_participant=True,
        local_rules_url="https://www.fairfaxcounty.gov/circuit/",
        publication_required=True,
    ),
    "arlington": CircuitCourt(
        name="Arlington County Circuit Court",
        fips_code="013",
        address=Address(
            street="1425 N Courthouse Rd",
            city="Arlington",
            zip_code="22201",
            county="Arlington",
        ),
        phone="(703) 228-7010",
        filing_fee_usd=53.00,
        vjefs_participant=True,
        local_rules_url="https://courts.arlingtonva.us/circuit-court/",
    ),
    "richmond city": CircuitCourt(
        name="Richmond City Circuit Court",
        fips_code="760",
        address=Address(
            street="400 N 9th St",
            city="Richmond",
            zip_code="23219",
            county="Richmond City",
        ),
        phone="(804) 646-6505",
        filing_fee_usd=53.00,
        vjefs_participant=False,
    ),
    "loudoun": CircuitCourt(
        name="Loudoun County Circuit Court",
        fips_code="107",
        address=Address(
            street="18 E Market St",
            city="Leesburg",
            zip_code="20176",
            county="Loudoun",
        ),
        phone="(703) 777-0270",
        filing_fee_usd=53.00,
        vjefs_participant=True,
    ),
    "virginia beach": CircuitCourt(
        name="Virginia Beach Circuit Court",
        fips_code="810",
        address=Address(
            street="2425 Nimmo Pkwy",
            city="Virginia Beach",
            zip_code="23456",
            county="Virginia Beach",
        ),
        phone="(757) 385-4181",
        filing_fee_usd=53.00,
        vjefs_participant=False,
    ),
    "prince william": CircuitCourt(
        name="Prince William County Circuit Court",
        fips_code="153",
        address=Address(
            street="9311 Lee Ave",
            city="Manassas",
            zip_code="20110",
            county="Prince William",
        ),
        phone="(703) 792-6015",
        filing_fee_usd=53.00,
        vjefs_participant=True,
    ),
    "henrico": CircuitCourt(
        name="Henrico County Circuit Court",
        fips_code="087",
        address=Address(
            street="4301 E Parham Rd",
            city="Henrico",
            zip_code="23228",
            county="Henrico",
        ),
        phone="(804) 501-4202",
        filing_fee_usd=53.00,
        vjefs_participant=False,
    ),
    "norfolk": CircuitCourt(
        name="Norfolk Circuit Court",
        fips_code="710",
        address=Address(
            street="100 St Pauls Blvd",
            city="Norfolk",
            zip_code="23510",
            county="Norfolk",
        ),
        phone="(757) 664-4380",
        filing_fee_usd=53.00,
        vjefs_participant=False,
    ),
    "chesterfield": CircuitCourt(
        name="Chesterfield County Circuit Court",
        fips_code="041",
        address=Address(
            street="9500 Courthouse Rd",
            city="Chesterfield",
            zip_code="23832",
            county="Chesterfield",
        ),
        phone="(804) 748-1241",
        filing_fee_usd=53.00,
        vjefs_participant=False,
    ),
    "alexandria": CircuitCourt(
        name="Alexandria Circuit Court",
        fips_code="510",
        address=Address(
            street="520 King St",
            city="Alexandria",
            zip_code="22314",
            county="Alexandria",
        ),
        phone="(703) 746-4044",
        filing_fee_usd=53.00,
        vjefs_participant=True,
    ),
    # -------------------------------------------------------------------
    # Roanoke metro area
    # -------------------------------------------------------------------
    "roanoke city": CircuitCourt(
        name="Roanoke City Circuit Court",
        fips_code="770",
        address=Address(
            street="315 Church Ave SW, 3rd Floor, Room 357",
            city="Roanoke",
            zip_code="24016",
            county="Roanoke City",
        ),
        phone="(540) 853-6702",
        filing_fee_usd=53.00,
        vjefs_participant=True,  # VJEFS participant
        local_rules_url="https://www.vacourts.gov/courts/circuit/Roanoke_City/home.html",
    ),
    "roanoke county": CircuitCourt(
        name="Roanoke County Circuit Court",
        fips_code="161",
        address=Address(
            street="305 E Main St, Suite 200",
            city="Salem",
            zip_code="24153",
            county="Roanoke County",
        ),
        phone="(540) 387-6205",
        filing_fee_usd=53.00,
        vjefs_participant=True,  # VJEFS participant
        local_rules_url="https://www.vacourts.gov/courts/circuit/Roanoke_County/home.html",
    ),
    "salem": CircuitCourt(
        name="Salem Circuit Court",
        fips_code="775",
        address=Address(
            street="2 E Calhoun St",
            city="Salem",
            zip_code="24153",
            county="Salem",
        ),
        phone="(540) 375-3067",
        filing_fee_usd=53.00,
        vjefs_participant=True,  # VJEFS participant
        local_rules_url="https://www.vacourts.gov/courts/circuit/Salem/home.html",
    ),
    "botetourt": CircuitCourt(
        name="Botetourt County Circuit Court",
        fips_code="023",
        address=Address(
            street="1 Main St",
            city="Fincastle",
            zip_code="24090",
            county="Botetourt",
        ),
        phone="(540) 473-8274",
        filing_fee_usd=53.00,
        vjefs_participant=False,  # Not a VJEFS participant
    ),
    "craig": CircuitCourt(
        name="Craig County Circuit Court",
        fips_code="045",
        address=Address(
            street="182 Main St",
            city="New Castle",
            zip_code="24127",
            county="Craig",
        ),
        phone="(540) 864-6141",
        filing_fee_usd=53.00,
        vjefs_participant=True,  # VJEFS participant
    ),
    "franklin county": CircuitCourt(
        name="Franklin County Circuit Court",
        fips_code="067",
        address=Address(
            street="275 S Main St, Suite 339",
            city="Rocky Mount",
            zip_code="24151",
            county="Franklin County",
        ),
        phone="(540) 483-3065",
        filing_fee_usd=53.00,
        vjefs_participant=False,  # Not a VJEFS participant
    ),
    "bedford county": CircuitCourt(
        name="Bedford County Circuit Court",
        fips_code="019",
        address=Address(
            street="123 E Main St, Suite 201",
            city="Bedford",
            zip_code="24523",
            county="Bedford County",
        ),
        phone="(540) 586-7632",
        filing_fee_usd=53.00,
        vjefs_participant=True,  # VJEFS participant
    ),
}


class JurisdictionError(Exception):
    """Raised when a jurisdiction cannot be resolved."""


def resolve_jurisdiction(address: Address) -> CircuitCourt:
    """Return the circuit court that has jurisdiction for *address*.

    Lookup is based on the ``county`` field of the address (which, for
    Virginia independent cities, is the city name).  The match is
    case-insensitive.

    Raises ``JurisdictionError`` if the county/city is not found in the
    registry.
    """
    key = (address.county or address.city).strip().lower()
    court = _COURT_REGISTRY.get(key)
    if court is None:
        raise JurisdictionError(
            f"No circuit court found for '{key}'. "
            "Please verify the county or independent city name and ensure "
            "it has been added to the court registry."
        )
    return court


def list_supported_jurisdictions() -> list[str]:
    """Return a sorted list of currently supported county/city keys."""
    return sorted(_COURT_REGISTRY.keys())
