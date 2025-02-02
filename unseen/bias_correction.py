"""Functions and command line program for bias correction."""

import argparse
import operator

import xarray as xr

from . import array_handling
from . import time_utils
from . import fileio
from . import general_utils


def get_bias(fcst, obs, method, time_period=None):
    """Calculate forecast bias.

    Args:
      fcst (xarray DataArray) : Forecast data
      obs (xarray DataArray) : Observational data
      method (str) : Bias removal method
      time_period (list) : Start and end dates (in YYYY-MM-DD format)
    """

    fcst_clim = time_utils.get_clim(
        fcst,
        ["ensemble", "init_date"],
        time_period=time_period,
        groupby_init_month=True,
    )

    obs_stacked = array_handling.stack_by_init_date(
        obs, init_dates=fcst["init_date"], n_lead_steps=fcst.sizes["lead_time"]
    )
    obs_clim = time_utils.get_clim(
        obs_stacked, "init_date", time_period=time_period, groupby_init_month=True
    )

    with xr.set_options(keep_attrs=True):
        if method == "additive":
            bias = fcst_clim - obs_clim
        elif method == "multiplicative":
            bias = fcst_clim / obs_clim
        else:
            raise ValueError(f"Unrecognised bias removal method {method}")

    bias.attrs["bias_correction_method"] = method
    if time_period:
        bias.attrs["bias_correction_period"] = "-".join(time_period)

    return bias


def remove_bias(fcst, bias, method):
    """Remove model bias.

    Args:
      fcst (xarray DataArray) : Forecast data
      bias (xarray DataArray) : Bias
      method (str) : Bias removal method
    """

    if method == "additive":
        op = operator.sub
    elif method == "multiplicative":
        op = operator.div
    else:
        raise ValueError(f"Unrecognised bias removal method {method}")

    with xr.set_options(keep_attrs=True):
        fcst_bc = op(fcst.groupby("init_date.month"), bias).drop("month")

    fcst_bc.attrs["bias_correction_method"] = bias.attrs["bias_correction_method"]
    try:
        fcst_bc.attrs["bias_correction_period"] = bias.attrs["bias_correction_period"]
    except KeyError:
        pass

    return fcst_bc


def _parse_command_line():
    """Parse the command line for input agruments"""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("fcst_file", type=str, help="Forecast file")
    parser.add_argument("obs_file", type=str, help="Observations file")
    parser.add_argument("var", type=str, help="Variable name")
    parser.add_argument(
        "method",
        type=str,
        choices=("multiplicative", "additive"),
        help="Bias correction method",
    )
    parser.add_argument("outfile", type=str, help="Output file")

    parser.add_argument(
        "--base_period",
        type=str,
        nargs=2,
        help="Start and end date for baseline (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--output_chunks",
        type=str,
        nargs="*",
        action=general_utils.store_dict,
        default={},
        help="Chunks for writing data to file (e.g. init_date=-1 lead_time=-1)",
    )

    args = parser.parse_args()

    return args


def _main():
    """Run the command line program."""

    args = _parse_command_line()

    ds_obs = fileio.open_file(args.obs_file, variables=[args.var])
    da_obs = ds_obs[args.var]

    ds_fcst = fileio.open_file(args.fcst_file, variables=[args.var])
    da_fcst = ds_fcst[args.var]

    bias = get_bias(da_fcst, da_obs, args.method, time_period=args.base_period)
    da_fcst_bc = remove_bias(da_fcst, bias, args.method)

    ds_fcst_bc = da_fcst_bc.to_dataset()
    infile_logs = {
        args.fcst_file: ds_fcst.attrs["history"],
        args.obs_file: ds_obs.attrs["history"],
    }
    ds_fcst_bc.attrs["history"] = fileio.get_new_log(infile_logs=infile_logs)

    if args.output_chunks:
        ds_fcst_bc = ds_fcst_bc.chunk(args.output_chunks)
    fileio.to_zarr(ds_fcst_bc, args.outfile)


if __name__ == "__main__":
    _main()
