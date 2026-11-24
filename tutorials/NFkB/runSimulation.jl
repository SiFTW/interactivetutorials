using Random

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

    # Identify parameters marked for cell-to-cell variability (distribute == 1)
    distribute_set = Set{String}()
    if isdefined(Main, :parametersDF) && "distribute" in names(parametersDF)
        for row in eachrow(parametersDF)
            if strip(string(row.distribute)) == "1"
                push!(distribute_set, strip(string(row.parameter)))
            end
        end
    end
    cv = isdefined(Main, :preCV) ? Float64(preCV) : 0.11
    n_cells = last_cell - first_cell + 1

    allParams=Array{Any}(undef, length(parameterNameList), last_cell)
    for cellIndex in first_cell:last_cell
        thisCellsParamVals=copy(originalParams)
        # Apply log-normal cell-to-cell heterogeneity when simulating multiple cells
        if n_cells > 1 && cv > 0.0
            sigma = sqrt(log(1.0 + cv^2))
            for j in 1:length(parameterNameList)
                if (parameterNameList[j] in distribute_set) && (thisCellsParamVals[j] isa Real) && (thisCellsParamVals[j] > 0)
                    mu_ln = log(Float64(thisCellsParamVals[j])) - 0.5 * sigma^2
                    thisCellsParamVals[j] = exp(mu_ln + sigma * randn())
                end
            end
        end
        allParams[:,cellIndex]=thisCellsParamVals
    end
    df = DataFrame(allParams,:auto)
    #add the variable names and save to a file
    insertcols!(df, 1, :names=>parameterNameList)

    CSV.write(folder*"/allParams_runSimulationNew.csv",df);
    allParamsOriginal=copy(allParams)
    for condIndex in 1:length(conditions)
        allParams=copy(allParamsOriginal)
        thisCondition = conditions[condIndex]
        
        println("Starting condition: "*thisCondition)
        odeName="odeModel"
        myFun=getfield(Main,Symbol(odeName))

        #define the function and the initial conditions
        f=ODEFunction(myFun)
        y0_init=zeros(length(syms))
        y0_init[findfirst(x->"MYD88"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"TRIF"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"TRAF6"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"IKK_off"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"TBK1"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"IRF3"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"CD14"==x,syms)] = 0.08 ;
        y0_init[findfirst(x->"cbswitch"==x,syms)] = 0 ;
        y0_init[findfirst(x->"C"==x,syms)] = 1 ;
        y0_init[findfirst(x->"B"==x,syms)] = 1 ;
        y0_init[findfirst(x->"M"==x,syms)] = 1 ;
        y0_init[findfirst(x->"TAK1"==x,syms)] = 0.1 ;
        y0_init[findfirst(x->"IKK_off"==x,syms)] = 200;
        y0_init[findfirst(x->"IKK_on"==x,syms)] = 0.1;
        y0_init[findfirst(x->"A20"==x,syms)] = 0.1;
        y0_init[findfirst(x->"tA20"==x,syms)] = 0.1;
        
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

        stiff_alg = if isdefined(Main, :AutoFiniteDiff)
            Rodas5P(autodiff=AutoFiniteDiff())
        elseif isdefined(DifferentialEquations, :AutoFiniteDiff)
            Rodas5P(autodiff=DifferentialEquations.AutoFiniteDiff())
        else
            Rodas5P()
        end

        for i in first_cell:last_cell
            println("starting cell: "*string(i))
            thisCellsParamVals=copy(allParams[:,i])
            thisCellsParamVals[BCRIndex]=BCRSSArray[condIndex]
            thisCellsParamVals[TLRIndex]=TLRSSArray[condIndex]
            thisCellsParamVals[NIKIndex]=NIKSSArray[condIndex]
      
            prob=ODEProblem(f,copy(y0_init),(0.0,maxTimeSS),thisCellsParamVals)

            solss=solve(prob, stiff_alg; saveat=100.0)
            println("Steady state found for cell: "*string(i))

            #dynamic phase, use SS solution as initial conditions
            y0_tc=collect(Float64, solss.u[end])
            y0_tc[y0_tc.<0].=0

            try
                thisCellsParamVals[BCRIndex]=BCRTCArray[condIndex]
                thisCellsParamVals[TLRIndex]=TLRTCArray[condIndex]
                thisCellsParamVals[NIKIndex]=NIKTCArray[condIndex]
                f=ODEFunction(myFun)
                prob=ODEProblem(f,y0_tc,(0.0,maxTimeTC),thisCellsParamVals)
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