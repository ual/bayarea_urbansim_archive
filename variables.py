import numpy as np
import pandas as pd
from urbansim.utils import misc
import urbansim.sim.simulation as sim
import datasources
from urbansim_defaults import utils
from urbansim_defaults import variables


#####################
# LOCAL ZONES VARIABLES
#####################


@sim.column('logsums', 'empirical_price')
def empirical_price(homesales, logsums):
    # put this here as a custom bay area indicator
    s = homesales.sale_price_flt.groupby(homesales.zone_id).quantile()
    # if price isn't present fill with median price
    s = s.reindex(logsums.index).fillna(s.quantile())
    s[s < 200] = 200
    return s


#####################
# COSTAR VARIABLES
#####################


@sim.column('costar', 'general_type')
def general_type(costar):
    return costar.PropertyType


@sim.column('costar', 'rent')
def rent(costar):
    return costar.averageweightedrent


@sim.column('costar', 'stories')
def stories(costar):
    return costar.number_of_stories


@sim.column('costar', 'node_id')
def node_id(parcels, costar):
    return misc.reindex(parcels.node_id, costar.parcel_id)


@sim.column('costar', 'zone_id')
def node_id(parcels, costar):
    return misc.reindex(parcels.zone_id, costar.parcel_id)


#####################
# JOBS VARIABLES
#####################


@sim.column('jobs', 'naics', cache=True)
def naics(jobs):
    return jobs.naics11cat


@sim.column('jobs', 'empsix', cache=True)
def empsix(jobs, settings):
    return jobs.naics.map(settings['naics_to_empsix'])


@sim.column('jobs', 'empsix_id', cache=True)
def empsix_id(jobs, settings):
    return jobs.empsix.map(settings['empsix_name_to_id'])


#####################
# HOMESALES VARIABLES
#####################


@sim.column('homesales', 'sale_price_flt')
def sale_price_flt(homesales):
    col = homesales.Sale_price.str.replace('$', '').\
        str.replace(',', '').astype('f4') / homesales.sqft_per_unit
    col[homesales.sqft_per_unit == 0] = 0
    return col


@sim.column('homesales', 'year_built')
def year_built(homesales):
    return homesales.Year_built


@sim.column('homesales', 'lot_size_per_unit')
def lot_size_per_unit(homesales):
    return homesales.Lot_size


@sim.column('homesales', 'sqft_per_unit')
def sqft_per_unit(homesales):
    return homesales.SQft


@sim.column('homesales', 'city')
def city(homesales):
    return homesales.City


@sim.column('homesales', 'zone_id')
def zone_id(parcels, homesales):
    return misc.reindex(parcels.zone_id, homesales.parcel_id)


@sim.column('homesales', 'node_id')
def node_id(parcels, homesales):
    return misc.reindex(parcels.node_id, homesales.parcel_id)


#####################
# PARCELS VARIABLES
#####################


# these are actually functions that take parameters, but are parcel-related
# so are defined here
@sim.injectable('parcel_average_price_ORIG', autocall=False)
def parcel_average_price_ORIG(use, quantile=.5):
    # I'm testing out a zone aggregation rather than a network aggregation
    # because I want to be able to determine the quantile of the distribution
    # I also want more spreading in the development and not keep it so localized
    if use == "residential":
        buildings = sim.get_table('buildings')
        return misc.reindex(buildings.
                            residential_price[buildings.general_type ==
                                              "Residential"].
                            groupby(buildings.zone_id).quantile(quantile),
                            sim.get_table('parcels').zone_id)

    

    if 'nodes' not in sim.list_tables():
        return pd.Series(0, sim.get_table('parcels').index)

    return misc.reindex(sim.get_table('nodes')[use],
                        sim.get_table('parcels').node_id)



@sim.injectable('parcel_average_price', autocall=False)
def parcel_average_price(use, quantile=.5):
    
    # price function attentive to inclusionary housing production. 
    # their price is not set by the hedonic prices in the zone, but
    # rather are pre-set relative to county-level HUD prices/targets fetched  
    # from a lookup table
    
    settings = sim.settings
    
    if use == "residential":
            
        # ## STEP 1: Get main tables

        parcels = sim.get_table('parcels')#.to_frame()
        buildings = sim.get_table('buildings')#.to_frame()

        from urbansim.developer import sqftproforma

        # ## STEP 2: Calculate generic revenue for inclusionary units affordable to 50% AMI
        # Below follows a simple calculation of revenue assuming units are built for 2-person households earning 50% of AMI pay 30% of their income on housing.


        ## for this lookup to work, the table needs to be registered in bayarea_urbansim/datasources.py

        bmr_prices = sim.get_table('HUD_below_market_rate_rent')

        # ## For now, county-level HUD 2-person households are used as a placeholder rent target assumption


        rev_per_mo_per_unit = bmr_prices['2-Person'].to_dict()

        # ## We need to translate the revenue per unit to a per square footage measure, in yearly terms
        # For this we need some translator constants. We grab from the model settings:

        SQFT_PER_UNIT = settings['residential_developer']['min_unit_size']
        CAP_RATE = sqftproforma.SqFtProForma().config.cap_rate

        # ## Get county-level expected sales *yearly revenue per sq ft* for the inclusionary square feet. 
        # 
        # Watch out for possible built-in conversions btw rent/own valuations--here we just assume sales.
        # 
        # TODO: we should use the existing rent / own conversion interface instead.
        # 
        # This yields values around $265 per square foot, give or take, maybe about a third to a half
        # of the market rate estimates currently, depending on the place. This seems low, but not crazy.

        rev_per_sqft = pd.Series(rev_per_mo_per_unit).apply(lambda x: x/ SQFT_PER_UNIT*12 / CAP_RATE).to_dict()


        # ## STEP 3: Push these county-level BMR revenue per sq ft estimates (generic) to the parcel level, going through county-to-city-to-parcel-level relationships.
        # 
        # 
        # Note that since the HUD numbers came at the county level, all parcels in the same county will
        # have the same estimated revenue per square foot for any inclusionary unit.
        # 
        # TODO: a bunch of these temporary variables we probably don't need to store in the parcel table--we just need them temporarily, so they could just be series.

        ## fetch a translator of arbitrary county ids in urbansim to FIPS codes, since many official data sources use FIPS codes
        county_id_to_fips=sim.get_injectable('county_id_to_fips')


        ## translate county id to FIPS, then map this to FIPS-level revenue per square foot calculated earlier. 

        parcels['incl_price_per_sf'] = parcels.county_id.fillna(-1).astype(np.int64).map(county_id_to_fips).map(rev_per_sqft)


        # ## STEP 4: Do the actual parcel-level weighting of revenue
        # 
        # First we take building-level `residential_price` data for residential buildings, take the median in the zone, and then push this number back to the parcel level. 
        # 
        ## TODO: res hedonic model needs to be run and simulated first to get a buildings table output; otherwise zeroes will result. This does not currently happen, so `residential_price` is 0 across the board. This needs to be fixed before any practical use and evaluation.
        ## so in theory this should return meaningful values, but `residential_price` is full of zeroes. 
        ## Fletcher or Mike probably have a more 'live' version of the buildings table. 
        ## Or we could just merge hedonic estimates on manually. Anyway, we continue the exercise just to get the bindings set up.

        market_rate = misc.reindex(buildings.residential_price[buildings.general_type == "Residential"].groupby(buildings.zone_id).quantile(quantile), sim.get_table('parcels').zone_id) 

        # Then we grab jurisdiction-level data on presence of inclusionary programs, for which purpose we have a lookup table / injectable called `inclusionary_rates` with a row for each `jurisdiction_id`. What are rates in these jurisdictions (at the city level)?
        # Note that these are placeholder values--we don't have a compilation of such rates, but ABAG is going to be collecting them over the summer. For now, we just assumed 12 percent for jurisdictions we know have SOME inclusionary program. This needs to be checked.


        ## load inclusionary rates, indexed on the 100+ jurisdiction ids. Whatever these jurisdictions actually are used to be stored on Paris.
        inclusionary_rates = sim.get_injectable('inclusionary_rates')
        s_inclusionary_rates = pd.Series(inclusionary_rates)

        # Then, flag cities w inclusionary rates larger than 0, and send this values to parcels.

        city_has_inclusionary = s_inclusionary_rates[s_inclusionary_rates>0].to_dict()
        parcels['incl_rate'] = parcels.city_id.fillna(-1).astype(np.int64).map(city_has_inclusionary).fillna(0)

        # the first 153,000 parcels are San Francisco ones, so they all have 12% incl rates

        # ## Result: A weighted avg of the market rate and inclusionary hsg constrained revenue assumption
        # Assuming a small-ish inclusionary rate, the number should be close to, but lower than, the market rate sales revenue per sf. This should be safe to calculate even for jurisdictions with no inclusionary policy--jurisdictions with zero inclusionary will just have a zero in the first term, and 100% of the market rate in the second.


        ## eg. .12           * 332.25                       + (1-.12)                 * 800
        return parcels['incl_rate'] * parcels['incl_price_per_sf'] + (1-parcels['incl_rate'])* market_rate

        # ## Further work needed:
        # * What this does is mainly change the cost structure of feasibility, meaning they are slightly less profitable in jurisdictions with inclsionary requirements. Note that there is no treatment of the incidence of this 'tax'--perhaps it is passed on to the consumer as much as being borne by the developer--if so, cost shifters should adjust overall prices levels for jurisdictions with such policies on the books. It goes without saying that the market rate prices need to NOT be all zeroes as they currently exist in my version of the buildings table. It may just be a matter of writing the output from the hedonic estimation to the table in the main datastore.
        # * Secondly, units actually produced in these jurisdictions need to be flagged and accounted for so they are visible in the household location choice model. A decision needs to be made as to the nature of this flag. It may be desirable to move to a unit-level representation--each unit becomes a row in a table and is maintained during the simulation, with appropriate attributes describing size, deed-restricted affordability, tenure, etc. Currently, some of this lives in the `buildings` table. If such a migration of unit of analysis were to happen, the hedonic model would need to leave deed restricted units alone.
        # * Third, there is no real distinction between owner and renter units. That may be desirable, even if Costa-Hawkins means less rental affordable units produced.


    if 'nodes' not in sim.list_tables():
        return pd.Series(0, sim.get_table('parcels').index)

    return misc.reindex(sim.get_table('nodes')[use],
                        sim.get_table('parcels').node_id)

    

@sim.injectable('parcel_sales_price_sqft_func', autocall=False)
def parcel_sales_price_sqft(use):
    s = parcel_average_price(use)
    if use == "residential": s *= 1.2
    return s

@sim.injectable('BMR_parcel_sales_price_sqft_func', autocall=False)
def BMR_parcel_sales_price_sqft(use):
    bmr_prices = sim.get_table('HUD_below_market_rate_rent')
    s = parcel_average_price(use)
    if use == "residential": s *= 1.2
    return s

### i put this in on 11/12 2014 bc feasibility model error:
### KeyError: 'injectable not found: parcel_sales_price_sqft'
#@sim.injectable('parcel_sales_price_sqft', autocall=False)
#def parcel_sales_price_sqft(use):
#    s = parcel_average_price(use)
#    if use == "residential": s *= 1.2
#    return s


@sim.injectable('parcel_is_allowed_func', autocall=False)
def parcel_is_allowed(form):
    settings = sim.settings
    form_to_btype = settings["form_to_btype"]
    # we have zoning by building type but want
    # to know if specific forms are allowed
    allowed = [sim.get_table('zoning_baseline')
               ['type%d' % typ] == 't' for typ in form_to_btype[form]]
    return pd.concat(allowed, axis=1).max(axis=1).\
        reindex(sim.get_table('parcels').index).fillna(False)


# actual columns start here
@sim.column('parcels', 'max_far', cache=True)
def max_far(parcels, scenario, scenario_inputs):
    return utils.conditional_upzone(scenario, scenario_inputs,
                                    "max_far", "far_up").\
        reindex(parcels.index).fillna(0)


@sim.column('parcels', 'max_dua', cache=True)
def max_dua(parcels, scenario, scenario_inputs):
    return utils.conditional_upzone(scenario, scenario_inputs,
                                    "max_dua", "dua_up").\
        reindex(parcels.index).fillna(0)


@sim.column('parcels', 'max_height', cache=True)
def max_height(parcels, zoning_baseline):
    return zoning_baseline.max_height.reindex(parcels.index).fillna(0)


@sim.column('parcels', 'residential_purchase_price_sqft')
def residential_purchase_price_sqft(parcels):
    return parcels.building_purchase_price_sqft


@sim.column('parcels', 'residential_sales_price_sqft')
def residential_sales_price_sqft(parcel_sales_price_sqft_func):
    return parcel_sales_price_sqft_func("residential")


# for debugging reasons this is split out into its own function
@sim.column('parcels', 'building_purchase_price_sqft')
def building_purchase_price_sqft():
    return parcel_average_price("residential") * .81


@sim.column('parcels', 'building_purchase_price')
def building_purchase_price(parcels):
    return (parcels.total_sqft * parcels.building_purchase_price_sqft).\
        reindex(parcels.index).fillna(0)


@sim.column('parcels', 'land_cost')
def land_cost(parcels):
    return parcels.building_purchase_price + parcels.parcel_size * 12.21


@sim.column('parcels', 'node_id')
def node_id(parcels):
    return parcels._node_id
