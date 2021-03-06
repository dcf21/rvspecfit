import os
os.environ['OMP_NUM_THREADS'] = '1'
import glob
import sys
import argparse
import time
import itertools
import concurrent.futures
from collections import OrderedDict

import matplotlib
import astropy.io.fits as pyfits
import numpy as np
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import astropy.table

from rvspecfit import fitter_ccf, vel_fit, spec_fit, utils


def make_plot(specdata, res_dict, title, fig_fname):
    """
    Make a plot with the spectra and fits

    Parameters:
    -----------
    specdata: SpecData object
        The object with specdata
    res_dict: list
        The list of dictionaries with fit results. The dictionaries must have yfit key
    title: string
        The figure title
    fig_fname: string
        The filename of the figure
    """
    alpha = 0.7
    line_width = 0.8
    plt.clf()
    plt.figure(1, figsize=(6, 6), dpi=300)
    plt.subplot(3, 1, 1)
    plt.plot(specdata[0].lam, specdata[0].spec, 'k-', linewidth=line_width)
    plt.plot(
        specdata[0].lam,
        res_dict['yfit'][0],
        'r-',
        alpha=alpha,
        linewidth=line_width)
    plt.title(title)
    plt.subplot(3, 1, 2)
    plt.plot(specdata[1].lam, specdata[1].spec, 'k-', linewidth=line_width)
    plt.plot(
        specdata[1].lam,
        res_dict['yfit'][1],
        'r-',
        alpha=alpha,
        linewidth=line_width)
    plt.subplot(3, 1, 3)
    plt.plot(specdata[2].lam, specdata[2].spec, 'k-', linewidth=line_width)
    plt.plot(
        specdata[2].lam,
        res_dict['yfit'][2],
        'r-',
        alpha=alpha,
        linewidth=line_width)
    plt.xlabel(r'$\lambda$ [$\AA$]')
    plt.tight_layout()
    plt.savefig(fig_fname)


def valid_file(fname):
    """
    Check if all required extensions are present if yes return true
    """
    exts = pyfits.open(fname)
    extnames = [_.name for _ in exts]

    arms = 'B', 'R', 'Z'
    prefs = 'WAVELENGTH', 'FLUX', 'IVAR', 'MASK'
    names0 = ['PRIMARY']
    reqnames = names0 + [
        '%s_%s' % (_, __) for _, __ in itertools.product(arms, prefs)
    ]
    missing = []
    for curn in reqnames:
        if curn not in extnames:
            missing.append(curn)
    if len(missing) != 0:
        print('WARNING Extensions %s are missing' % (','.join(missing)))
        return False
    return True


def proc_desi(fname, ofname, fig_prefix, config, fit_targetid):
    """
    Process One single file with desi spectra

    Parameters:
    -----------
    fname: str
        The filename with the spectra to be fitted
    ofname: str
        The filename where the table with parameters will be stored
    fig_prefix: str
        The prefix where the figures will be stored
    fit_targetid: int
        The targetid to fit. If none fit all.
    """

    options = {'npoly': 10}

    print('Processing', fname)
    if not valid_file(fname):
        return
    tab = pyfits.getdata(fname, 'FIBERMAP')
    mws = tab['MWS_TARGET']
    targetid = tab['TARGETID']
    brick_name = tab['BRICKNAME']
    xids = np.nonzero(mws)[0]
    setups = ('b', 'r', 'z')
    fluxes = {}
    ivars = {}
    waves = {}
    masks = {}
    for s in setups:
        fluxes[s] = pyfits.getdata(fname, '%s_FLUX' % s.upper())
        ivars[s] = pyfits.getdata(fname, '%s_IVAR' % s.upper())
        masks[s] = pyfits.getdata(fname, '%s_MASK' % s.upper())
        waves[s] = pyfits.getdata(fname, '%s_WAVELENGTH' % s.upper())

    columns = [
        'brickname', 'target_id', 'vrad', 'vrad_err', 'logg', 'teff', 'vsini',
        'feh', 'alpha', 'chisq_tot'
    ]
    for s in setups:
        columns.append('sn_%s' % s)
        columns.append('chisq_%s' % s)
        columns.append('chisq_c_%s' % s)
    outdict = OrderedDict()
    for c in columns:
        outdict[c] = []
    large_error = 1e9
    for curid in xids:
        specdata = []
        curbrick = brick_name[curid]
        curtargetid = targetid[curid]
        if fit_targetid is not None and curtargetid != fit_targetid:
            continue

        fig_fname = fig_prefix + '_%s_%d.png' % (curbrick, curtargetid)
        sns = {}
        chisqs = {}
        for s in setups:
            spec = fluxes[s][curid]
            curivars = ivars[s][curid]
            badmask = (curivars <= 0) | (masks[s][curid] > 0)
            curivars[badmask] = 1. / large_error**2
            espec = 1. / curivars**.5
            sns[s] = np.nanmedian(spec / espec)
            specdata.append(
                spec_fit.SpecData(
                    'desi_%s' % s, waves[s], spec, espec, badmask=badmask))
        t1 = time.time()
        res = fitter_ccf.fit(specdata, config)
        t2 = time.time()
        paramDict0 = res['best_par']
        fixParam = []
        if res['best_vsini'] is not None:
            paramDict0['vsini'] = res['best_vsini']
        res1 = vel_fit.process(
            specdata,
            paramDict0,
            fixParam=fixParam,
            config=config,
            options=options)
        t3 = time.time()
        chisq_cont_array = spec_fit.get_chisq_continuum(
            specdata, options=options)
        t4 = time.time()
        outdict['brickname'].append(curbrick)
        outdict['target_id'].append(curtargetid)
        outdict['vrad'].append(res1['vel'])
        outdict['vrad_err'].append(res1['vel_err'])
        outdict['logg'].append(res1['param']['logg'])
        outdict['teff'].append(res1['param']['teff'])
        outdict['alpha'].append(res1['param']['alpha'])
        outdict['feh'].append(res1['param']['feh'])
        outdict['chisq_tot'].append(sum(res1['chisq_array']))
        for i, s in enumerate(setups):
            outdict['chisq_%s' % s].append(res1['chisq_array'][i])
            outdict['chisq_c_%s' % s].append(float(chisq_cont_array[i]))
            outdict['sn_%s' % (s, )].append(sns[s])

        outdict['vsini'].append(res1['vsini'])

        title = 'logg=%.1f teff=%.1f [Fe/H]=%.1f [alpha/Fe]=%.1f Vrad=%.1f+/-%.1f' % (
            res1['param']['logg'], res1['param']['teff'], res1['param']['feh'],
            res1['param']['alpha'], res1['vel'], res1['vel_err'])
        make_plot(specdata, res1, title, fig_fname)
    outtab = astropy.table.Table(outdict)
    outtab.write(ofname, overwrite=True)


def proc_desi_wrapper(*args, **kwargs):
    try:
        ret = proc_desi(*args, **kwargs)
    except:
        print('failed with these arguments', args, kwargs)
        raise


proc_desi_wrapper.__doc__ = proc_desi.__doc__


def proc_many(files,
              oprefix,
              fig_prefix,
              config=None,
              nthreads=1,
              overwrite=True,
              targetid=None):
    """
    Process many spectral files

    Parameters:
    -----------
    mask: string
        The filename mask with spectra, i.e path/*fits
    oprefix: string
        The prefix where the table with measurements will be stored
    fig_prefix: string
        The prfix where the figures will be stored
    targetid: integer
        The targetid to fit (the rest will be ignored)
    """
    config = utils.read_config(config)

    if nthreads > 1:
        parallel = True
    else:
        parallel = False

    if parallel:
        poolEx = concurrent.futures.ProcessPoolExecutor(nthreads)
    res = []
    for f in files:
        fname = f.split('/')[-1]
        ofname = oprefix + 'outtab_' + fname
        if (not overwrite) and os.path.exists(ofname):
            print('skipping, products already exist', f)
            continue
        arg = (f, ofname, fig_prefix, config, targetid)
        if parallel:
            res.append(
                poolEx.submit(proc_desi_wrapper, 
                            *arg)
            )
        else:
            proc_desi_wrapper(*arg)
    
    if parallel:
        try:
            poolEx.shutdown(wait=True)
        except KeyboardInterrupt:
            for r in res:
                r.cancel()
            poolEx.shutdown(wait=False)
            raise
            


def main(args):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--nthreads',
        help='Number of threads for the fits',
        type=int,
        default=1)

    parser.add_argument(
        '--config',
        help='The filename of the configuration file',
        type=str,
        default=None)

    parser.add_argument(
        '--input_files',
        help='Space separated list of files to process',
        type=str,
        default=None,
        nargs='+')
    parser.add_argument(
        '--input_file_from',
        help='Read the list of spectral files from the text file',
        type=str,
        default=None)

    parser.add_argument(
        '--output_dir',
        help='Output directory for the tables',
        type=str,
        default=None,
        required=True)
    parser.add_argument(
        '--targetid',
        help='Fit only a given targetid',
        type=int,
        default=None,
        required=False)
    parser.add_argument(
        '--output_tab_prefix',
        help='Prefix of output table files',
        type=str,
        default='outtab',
        required=False)

    parser.add_argument(
        '--figure_dir',
        help='Prefix for the fit figures, i.e. fig_folder/',
        type=str,
        default='./')
    parser.add_argument(
        '--figure_prefix',
        help='Prefix for the fit figures, i.e. im',
        type=str,
        default='fig',
        required=False)

    parser.add_argument(
        '--overwrite',
        help=
        'If enabled the code will overwrite the existing products, otherwise it will skip them',
        action='store_true',
        default=False)

    args = parser.parse_args(args)
    input_files = args.input_files
    input_file_from = args.input_file_from

    oprefix = args.output_dir + '/' + args.output_tab_prefix
    fig_prefix = args.figure_dir + '/' + args.figure_prefix
    nthreads = args.nthreads
    config = args.config
    targetid = args.targetid

    if input_files is not None and input_file_from is not None:
        raise Exception(
            'You can only specify --input_files OR --input_file_from options but not both of them simulatenously'
        )

    if input_files is not None:
        files = input_files
    elif input_file_from is not None:
        files = []
        with open(input_file_from, 'r') as fp:
            for l in fp:
                files.append(l.rstrip())
    else:
        raise Exception('You need to specify the spectra you want to fit')

    proc_many(
        files,
        oprefix,
        fig_prefix,
        nthreads=nthreads,
        overwrite=args.overwrite,
        config=config,
        targetid=targetid)


if __name__ == '__main__':
    main(sys.argv[1:])
