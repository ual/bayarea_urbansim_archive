import models
import urbansim.sim.simulation as sim

import logging
from urbansim.utils.logutil import log_to_stream, set_log_level
set_log_level(logging.DEBUG)
log_to_stream()

sim.run(["neighborhood_vars"])
sim.run(["rsh_simulate", "nrh_simulate"])

%%prun -q -D hlcm_estimate.prof
orca.run(["hlcm_estimate"])
