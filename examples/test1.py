import astropy.io.fits as pyfits
import numpy as np
import sys
import time
import matplotlib.pyplot as plt
sys.path.append('../')
import spec_fit

setup = 'test'

config=spec_fit.read_config()

# read data
dat=pyfits.getdata('spec-0266-51602-0031.fits')
err=dat['ivar']
err=1./err**.5
err[~np.isfinite(err)]=1e40


# construct specdata object
specdata=[spec_fit.SpecData('sdss1',10**dat['loglam'],
                        dat['flux'],err)]
rot_params=None
resols_params=None

params_list=[[4000,3,-1,0],[5000,3,-1,0],[6000,2,-2,0],[5500,5,0,0]]
vel_grid=np.linspace(-600,600,1000)
options={'npoly':10}

t1=time.time()
spec_fit.find_best(specdata, vel_grid, params_list, rot_params, resols_params, 
          options=options, config=config)

t2=time.time()
res=(spec_fit.find_best(specdata, vel_grid, params_list, rot_params, resols_params, 
          options=options, config=config))
bestv,bestpar, bestchi, velerr = [res[_] for _ in ['bestvel','bestparam','bestchi','velerr']]
t3=time.time()
print(t2-t1,t3-t2)

rot_params =(300,)
chisq,yfit=spec_fit.get_chisq(specdata, bestv, bestpar, rot_params, resols_params, 
                        options=options, config=config,getModel=True)
plt.plot(specdata[0].lam,specdata[0].spec,'k')
plt.plot(specdata[0].lam,yfit[0],'r')
plt.savefig('test1.png')



# Test the fit with the resolution matrix 
rot_params = None
resol_mat  = spec_fit.construct_resol_mat(specdata[0].lam, 50)
resols_params = {'sdss1':resol_mat}
chisq,yfit=spec_fit.get_chisq(specdata, bestv, bestpar, rot_params, resols_params, 
                        options=options, config=config,getModel=True)
plt.plot(specdata[0].lam,specdata[0].spec,'k')
plt.plot(specdata[0].lam,yfit[0],'r')
plt.savefig('test2.png')