function runSimulation(first_cell, last_cell, conditions,folder,BCRSSArray,BCRTCArray,TLRSSArray,TLRTCArray,NIKSSArray,NIKTCArray)
    mkpath(folder)
    #now lets loop through and solve the cell
    TCLength=1000*60
    maximumAttemptsAtSS=10
    inputFuncs=[t->0,t->0]
    include("variableNames.jl")
    include("scanIncludes.jl")
    originalParams=copy(paramVals)
    BCRIndex=findfirst(x -> x=="k3_signal-BCR", parameterNameList)
    TLRIndex=findfirst(x -> x=="k2_LPSmod-TLR", parameterNameList)
    NIKIndex=findfirst(x -> x=="nik_deg_mod-NFkB", parameterNameList)

    


    allParams=[]
    allParams=Array{Any}(undef, size(parametersDF,1), last_cell)
    for cellIndex in first_cell:last_cell
        thisCellsParamVals=copy(originalParams)            

        #println(thisCellsParamVals)
        allParams[:,cellIndex]=thisCellsParamVals
    end
    df = DataFrame(allParams,:auto)
    #add the variable names and save to a file
    insertcols!(df, 1, :names=>parameterNameList)

    CSV.write(folder*"/allParams_runSimulationNew.csv",df);
    #println(size(allParams))
    #println(allParams[1])
    allParamsOriginal=copy(allParams)
    for condIndex in 1:length(conditions)
        allParams=copy(allParamsOriginal)
        thisCondition = conditions[condIndex]
        #TODO: consider making a condition scaling factor array here and just multiplying all prameters by it every time.
        
        println("Starting condition: "*thisCondition)
        odeName="odeModel"
        myFun=getfield(Main,Symbol(odeName))

        #define the function and the initial conditions
        f=ODEFunction(myFun)
        y0=zeros(length(syms))
        
        y0=zeros(size(syms))
        y0[findfirst(x->"MYD88"==x,syms)] = 0.1 ;
        y0[findfirst(x->"TRIF"==x,syms)] = 0.1 ;
        y0[findfirst(x->"TRAF6"==x,syms)] = 0.1 ;
        y0[findfirst(x->"IKK_off"==x,syms)] = 0.1 ;
        y0[findfirst(x->"TBK1"==x,syms)] = 0.1 ;
        y0[findfirst(x->"IRF3"==x,syms)] = 0.1 ;
        y0[findfirst(x->"CD14"==x,syms)] = 0.08 ;
        y0[findfirst(x->"cbswitch"==x,syms)] = 0 ;
        y0[findfirst(x->"C"==x,syms)] = 1 ;
        y0[findfirst(x->"B"==x,syms)] = 1 ;
        y0[findfirst(x->"M"==x,syms)] = 1 ;
        y0[findfirst(x->"TAK1"==x,syms)] = 0.1 ;
        y0[findfirst(x->"IKK_off"==x,syms)] = 200;
        y0[findfirst(x->"IKK_on"==x,syms)] = 0.1;
        y0[findfirst(x->"A20"==x,syms)] = 0.1;
        y0[findfirst(x->"tA20"==x,syms)] = 0.1;
        
        paramsListInThisCondition=paramsToChange[condIndex]
        modifyListInThisCondition=modifyAmount[condIndex]

        for thisParamIndex in 1:length(paramsListInThisCondition)
            thisParam=paramsListInThisCondition[thisParamIndex]
            thisParamsIndexInParamList=findfirst(x->x==thisParam,parameterNameList)
            if isnothing(thisParamsIndexInParamList)
                suggestions = filter(x -> occursin(lowercase(first(split(thisParam, "-"))), lowercase(x)), parameterNameList)
                hint = isempty(suggestions) ? "" : " Did you mean one of: " * join(first(suggestions, 5), ", ")
                error("Parameter \"$(thisParam)\" not found in parameterNameList! Check spelling/capitalisation.$(hint)")
            end
            allParams[thisParamsIndexInParamList,:]=allParams[thisParamsIndexInParamList,:].*modifyListInThisCondition[thisParamIndex]
        end  
        df = DataFrame(allParams,:auto)
        #add the variable names and save to a file
        insertcols!(df, 1, :names=>parameterNameList)
        CSV.write(folder*"/allParams_runSimulationNew_"*thisCondition*".csv",df);

#         Threads.@threads for i in first_cell:last_cell
        for i in first_cell:last_cell
            #figure out the name of this cell's ode file
            
            #DISTRIBUTE PARAMS
            
            println("starting cell: "*string(i))
            thisCellsParamVals=copy(allParams[:,i])
            thisCellsParamVals[BCRIndex]=BCRSSArray[condIndex]
            thisCellsParamVals[TLRIndex]=TLRSSArray[condIndex]
            thisCellsParamVals[NIKIndex]=NIKSSArray[condIndex]
      
    #     #now write this condition's CSV file to a folder of cells
    #     CSV.write(generatedCSVLocation*"/parameters_"*string(conditions[condIndex])*".csv", thisCondParamFile)
            prob=ODEProblem(f,y0,(0.0,maxTimeSS),thisCellsParamVals)

            stiff_alg = if isdefined(Main, :AutoFiniteDiff)
                Rodas5P(autodiff=AutoFiniteDiff())
            elseif isdefined(DifferentialEquations, :AutoFiniteDiff)
                Rodas5P(autodiff=DifferentialEquations.AutoFiniteDiff())
            else
                Rodas5P()
            end

            solss=solve(prob, stiff_alg; saveat=100.0)
            println("Steady state found for cell: "*string(i))

            #dynamic phase, use SS solution as initial conditions
            y0=collect(Float64, solss.u[end])
            y0[y0.<0].=0

            #CSV.write(generatedCSVLocation*"/parameters_"*string(conditions[condIndex])*"_cell_"*string(i)*".csv", DataFrame(thisCellsParamVals,:auto))
            try
                thisCellsParamVals[BCRIndex]=BCRTCArray[condIndex]
                thisCellsParamVals[TLRIndex]=TLRTCArray[condIndex]
                thisCellsParamVals[NIKIndex]=NIKTCArray[condIndex]
                f=ODEFunction(myFun)
                prob=ODEProblem(f,y0,(0.0,maxTimeTC),thisCellsParamVals)
                println("Solving equations for dynamic time course for cell:"*string(i))
                sol=solve(prob, stiff_alg; reltol=1e-6, saveat=1.0)
                #save("outputs/sol_"*thisCondition*"_cell_"*string(i)*".jld2", "solution", sol)
                df = DataFrame(Float64.(reduce(hcat, sol.u)),:auto)
                #add the variable names and save to a file
                insertcols!(df, 1, :names=>syms)
                CSV.write(folder*"/sol_"*thisCondition*"_cell_"*string(i)*".csv",df);
            catch e
                println("error:")
                println(e)
            end

        end
        println("all cells done in condition: "*thisCondition)

    end
end