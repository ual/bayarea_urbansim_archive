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
            
        parcels = sim.get_table('parcels')#.to_frame()
        buildings = sim.get_table('buildings')#.to_frame()
        
        ## segment inclusionary jurisdictions

        ## STEP  1: fetch parcel-level rates--some of these may be zero, which is OK.
        ## Then there will just be no inclusionary units built for these jurisdictions

        #parcels['inclusionary_rate']=parcels.city_id.map(inclusionary_rates)

        ## STEP 2: Calculate revenue for inclusionary cut

        bmr_prices = sim.get_table('HUD_below_market_rate_rent')

        ## for now, county-level HUD 2-person households are used as a placeholder
        ## rent target assumption
        
        rev_per_mo_per_unit = bmr_prices['2-Person'].to_dict()
        
        ## we need to translate the revenue per unit to a per square footage measure
        ## TODO: There are likely real values in urbansim somewhere for the below constants.
        ## Just keep thse for now as placeholder values
        
        SQFT_PER_UNIT = 1000 
        CAP_RATE = .06
        
        ## get county-level expected sales *revenue per SF* for the inclusionary square feet. 
        ## watch out for possible built-in conversions btw rent/own valuations.
        ## this yields values around $200 per square foot, give or take, about *a third*
        ## of the market rate estimates currently. This seems low, but not crazy.

        rev_per_mo_per_sqft = pd.Series(rev_per_mo_per_unit).\
            apply(lambda x: x/ SQFT_PER_UNIT*12 / CAP_RATE).to_dict()


        ## STEP 3: Push these county-level BMR revenue estimates (generic) to the parcel level, going
        ## through county-to-city-to-parcel-level relationships. Probably not necessary to actually
        ## store on the parcels table

        county_id_to_fips=sim.get_injectable('county_id_to_fips')
        
        parcels['incl_price_per_sf'] = parcels.county_id.fillna(-1).\
        astype(np.int64).map(county_id_to_fips).map(rev_per_mo_per_sqft)


        ## STEP 4: Do the actual parcel-level weighting of revenue

        # A: Market rate
        market_rate = misc.reindex(buildings.residential_price[buildings.general_type == "Residential"].\
                            groupby(buildings.zone_id).quantile(quantile),
                            sim.get_table('parcels').zone_id) 

     
        ## B: Inclusionary rates
        
        inclusionary_rates = sim.get_injectable('inclusionary_rates')
        parcels['inclusionary_rate']=parcels.city_id.map(inclusionary_rates)
        s_inclusionary_rates = pd.Series(inclusionary_rates)
        
        ## get list of cities w inclusionary rates larger than 0
        inclusionary_cities = s_inclusionary_rates[s_inclusionary_rates>0].to_dict().keys()

        city_has_inclusionary = s_inclusionary_rates[s_inclusionary_rates>0].to_dict()
        parcels['incl_rate'] = parcels.city_id.fillna(-1).astype(np.int64).map(city_has_inclusionary).fillna(0)
        

        ## Actual weighting. This should be fine--jurisdictions with zero inclusionary
        ## will have a zero in the first term, and 100% of the market rate in the second.

        return parcels['incl_rate'] * parcels['incl_price_per_sf'] + (1-parcels['incl_rate'])* market_rate


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
